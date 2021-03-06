#!/bin/bash

# NOTE: currently buildbot is installed as an editable package to ~/opt/buildbot_venv. This means
# that any source code changes are immediately visible and one just needs to do a buildbot restart
# in order to pick them up.
#
# Thus most of the time it's not necessary to run this script.
#
# It is recommended to run it after upgrading buildbot to synchronize the binaries of the
# buildbot www-related packages.

set -e
set -x

# make sure we get the right version number
git fetch kdab --tags
git fetch origin --tags

# required for yarn
# TODO: looks like this does not work from a completely clean git repository.
# export PATH="$PATH:$PWD/node_modules/.bin/"
# npm install yarn webpack-cli less-loader css-loader

# This will build all frontend packages in a custom virtualenv maintained by the Makefile.
# This is what upstream uses to run their frontend tests, so it should work for us too.
# rm -rf .venv
# make frontend

source ~/opt/buildbot_venv/bin/activate

pip install \
    -e pkg \
    -e 'master[tls,test,docs]' \
    -e 'worker[test]' \
    buildbot-www \
    buildbot-badges \
    buildbot-console-view \
    buildbot-grid-view \
    buildbot-waterfall-view \
    buildbot-wsgi-dashboards

pip install -r requirements-kdabci.txt
