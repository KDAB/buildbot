# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members

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
from buildbot.status.words import UsageError, StatusBot

from buildbot import interfaces
from buildbot.interfaces import IStatusReceiver
from buildbot.status.base import StatusReceiver
from buildbot.status import base
from twisted.python import log, failure
from twisted.words.protocols.jabber.jid import JID
from zope.interface import implements

def avoid_shlex_split_because_xmpp_is_all_unicode(s):
    return s.split()
from buildbot.status import words
words.shlex.split = avoid_shlex_split_because_xmpp_is_all_unicode

class JabberMucContact(words.IRCContact):
    implements(IStatusReceiver)

    def __init__(self, channel, jid):
        words.IRCContact.__init__(self, channel, jid)
        self.channel = channel
        self.roomJID = jid

    def describeUser(self, user):
        return "Jabber user <%s> on %s" % (user, self.dest)

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
        if not self._isMuted():
            self.channel.groupChat(self.roomJID, message)

class JabberStatusBot(words.StatusBot, MUCClient):

    contactClass = JabberMucContact

    def __init__(self, mucs, categories, notify_events, **kwargs):
        # colors make sense for IRC only atm, so disable them for Jabber
        words.StatusBot.__init__(self, useColors=False, **kwargs)
        MUCClient.__init__(self)

        self.mucs = mucs
        self.categories = categories
        self.notify_events = notify_events
        self.contacts = {}
        self.counter = 0

    def connectionInitialized(self):
        MUCClient.connectionInitialized(self)
        for m in self.mucs:
            (muc, nick) = (m['muc'], m['nick'])
            self.join(JID(muc), nick)

    def connectionLost(self, reason):
        MUCClient.connectionLost(self, reason)
        log.msg("Got disconnected: {0}".format(reason))

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

class Jabber(base.StatusReceiver, XMPPClient):
    """
    I represent a status target for Jabber services.

    It can be used to connect to a Jabber server.
    A list of MUCs can be specified that will be joined on logon.

    @type host: string
    @cvar host: the host where the Jabber service lives, e.g. "localhost"
    @type jid: string
    @cvar jid: the JID that is used to login, in the form "nick@host/resource"
    @type password: string
    @cvar password: password that is used to login to the service
    @type mucs: list of dicts
    @ivar mucs: MUC list, specifying the chat and the nick to be used,
        e.g. [{'muc':chat@conference.example.com,'nick':'user1'}]
    @type port: integer
    @ivar port: port of the Jabber service (optional)
    """

    implements(IStatusReceiver)

    debug = False

    compare_attrs = ['host', 'jid', 'password', 'mucs', 'port',
      'allowForce', 'categories', 'notify_events', 'showBlameList']

    def __init__(self, host, jid, password, mucs, port=5222,
                 allowForce=False, categories=None, notify_events={},
                 noticeOnChannel=False, useRevisions=False, showBlameList=False):
        assert allowForce in (True, False)

        # Stash these so we can detect changes later.
        self.password = password
        assert(isinstance(mucs, list))
        self.mucs = mucs
        self.allowForce = allowForce
        self.categories = categories
        self.notify_events = notify_events

        if not isinstance(jid, JID):
            jid = JID(str(jid))
        XMPPClient.__init__(self, jid, self.password, host, port)
        self.logTraffic = self.debug
        ping_handler = PingHandler()
        self.addHandler(ping_handler)
        ping_handler.setHandlerParent(self)
        muc_handler = JabberStatusBot(self.mucs, self.categories,
                                      self.notify_events, noticeOnChannel=noticeOnChannel,
                                      useRevisions=useRevisions, showBlameList=showBlameList
                                      )
        self.addHandler(muc_handler)
        muc_handler.setHandlerParent(self)
        self.channel = muc_handler

    def setServiceParent(self, parent):
        base.StatusReceiver.setServiceParent(self, parent)
        self.channel.status = parent
        self.channel.master = parent.master
        if self.allowForce:
            self.channel.control = interfaces.IControl(self.master)
        XMPPClient.setServiceParent(self, parent)
