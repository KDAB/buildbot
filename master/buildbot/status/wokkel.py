# Deliver build status to a Jabber MUC (multi-user chat room).

from __future__ import absolute_import

# Twisted Words 11.0 lacks high-level support for XMPP.  For that, we
# use Wokkel.  This module should eventually be merged into words.py
# when Twisted Words integrates the features we need from Wokkel.
from wokkel.client import XMPPClient
from wokkel.muc import MUCClient
from wokkel.ping import PingHandler

# We can reuse words.py's concept of `broadcast contacts' in XMPP.  A
# channel in IRC is a MUC in XMPP.
from buildbot.status.words import Contact, IChannel, UsageError

from buildbot import interfaces
from buildbot.interfaces import IStatusReceiver
from buildbot.status.base import StatusReceiver
from twisted.python import log, failure
from twisted.words.protocols.jabber.jid import JID
from zope.interface import implements

def avoid_shlex_split_because_xmpp_is_all_unicode(s):
    return s.split()
from buildbot.status import words
words.shlex.split = avoid_shlex_split_because_xmpp_is_all_unicode

class JabberMucContact(Contact):
    implements(IStatusReceiver)

    def __init__(self, channel, jid):
        Contact.__init__(self, channel)
        self.roomJID = jid

    def act(self, action):
        self.send("/me %s" % action)

    def handleMessage(self, message, who):
        message = message.lstrip()
        if self.silly.has_key(message):
            return self.doSilly(message)

        parts = message.split(None, 1)
        if len(parts) == 1:
            parts = parts + [u'']
        cmd, args = parts

        meth = self.getCommandMethod(cmd)
        if not meth and message[-1] == '!':
            meth = self.command_EXCITED

        error = None
        try:
            if meth:
                meth(args.strip(), who)
        except UsageError, e:
            self.send(str(e))
        except:
            f = failure.Failure()
            log.err(f)
            error = "Something bad happened (see logs): %s" % f.type

        if error:
            try:
                self.send(error)
            except:
                log.err()

        self.channel.counter += 1

    def send(self, message):
        if not self.muted:
            self.channel.groupChat(self.roomJID, message)

class JabberStatusBot(MUCClient):
    implements(IChannel)

    def __init__(self, mucs, categories, notify_events,
      showBlameList=False):
        MUCClient.__init__(self)
        self.mucs = mucs
        self.categories = categories
        self.notify_events = notify_events
        self.showBlameList = showBlameList
        self.contacts = {}
        self.counter = 0

    def addContact(self, jid, contact):
        self.contacts[jid] = contact

    def connectionInitialized(self):
        MUCClient.connectionInitialized(self)
        for m in self.mucs:
            (muc, nick) = (m['muc'], m['nick'])
            self.join(JID(muc), nick)

    def deleteContact(self, jid):
        del self.contacts[jid]

    def getContact(self, jid):
        if jid in self.contacts:
            return self.contacts[jid]
        new_contact = JabberMucContact(self, jid)
        self.contacts[jid] = new_contact
        return new_contact

    def join(self, roomJID, nick, historyOptions=None, password=None):
        def new_contact_on_join(room):
            self.getContact(room.roomJID)
            return room
        d = MUCClient.join(self, roomJID, nick, historyOptions,
          password)
        d.addCallback(new_contact_on_join)

    def receivedGroupChat(self, room, user, message):
        try:
            # Ignore our own messages sent to the MUC.  'tis a bit silly
            # that we can fire our own received message handler...
            if user.nick == room.nick:
                return
        except AttributeError:
            return # Some kind of status message.  Ignore this, too.
        contact = self.getContact(room.roomJID)
        body = message.body
        if body.startswith("/me"):
            contact.handleAction(body, user.nick)
        if body.startswith("%s:" % room.nick) or \
          body.startswith("%s," % room.nick):
            body = body[len("%s:" % room.nick):]
            contact.handleMessage(body, user.nick)

class Jabber(StatusReceiver, XMPPClient):
    implements(IStatusReceiver)

    debug = False

    compare_attrs = ['host', 'jid', 'password', 'mucs', 'port',
      'allowForce', 'categories', 'notify_events', 'showBlameList']

    def __init__(self, host, jid, password, mucs, port=5222,
      allowForce=False, categories=None, notify_events={},
      showBlameList=True):
        assert allowForce in (True, False)

        # Stash these so we can detect changes later.
        self.password = password
        self.mucs = mucs
        self.allowForce = allowForce
        self.categories = categories
        self.notify_events = notify_events
        self.showBlameList = showBlameList

        if not isinstance(jid, JID):
            jid = JID(str(jid))
        XMPPClient.__init__(self, jid, self.password, host, port)
        self.logTraffic = self.debug
        ping_handler = PingHandler()
        self.addHandler(ping_handler)
        ping_handler.setHandlerParent(self)
        muc_handler = JabberStatusBot(self.mucs, self.categories,
          self.notify_events, self.showBlameList)
        self.addHandler(muc_handler)
        muc_handler.setHandlerParent(self)
        self.channel = muc_handler

    def setServiceParent(self, parent):
        self.channel.status = parent.getStatus()
        self.channel.status.master = self.channel.status.master
        if self.allowForce:
            self.channel.control = interfaces.IControl(parent)
        XMPPClient.setServiceParent(self, parent)
