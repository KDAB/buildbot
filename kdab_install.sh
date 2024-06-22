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
export PATH="$PATH:$PWD/node_modules/.bin/"
npm install yarn

# This will build all frontend packages in a custom virtualenv maintained by the Makefile.
# This is what upstream uses to run their frontend tests, so it should work for us too.
rm -rf .venv
make frontend

rm -rf ~/opt/buildbot_venv/
virtualenv --python=/usr/bin/python3 ~/opt/buildbot_venv/

source ~/opt/buildbot_venv/bin/activate

pip install \
    -e pkg \
    -e 'master[tls,test,docs]' \
    -e 'worker[test]'

pip install \
    -e www/base \
    -e www/console_view \
    -e www/grid_view \
    -e www/waterfall_view \
    -e www/wsgi_dashboards \
    -e www/badges \
    -e www/codeparameter

pip install -r requirements-kdabci.txt
