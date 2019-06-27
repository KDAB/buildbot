#!/bin/bash

set -e
set -x

# required for yarn
export PATH="$PATH:$PWD/node_modules/.bin"

PREFIX=~/opt/buildbot

function py_install() {
  python3 setup.py build || exit 1
  python3 setup.py install --prefix=$PREFIX || exit 1
}

cd master/
py_install
cd ../

pip3 install --system --prefix=$PREFIX -e pkg || exit 1
pip3 install --system --prefix=$PREFIX mock || exit 1

pushd www/data_module
yarn install
node_modules/.bin/gulp prod --no-tests
popd

# copied from Buildbot's Makefile, adapt as required
# DISABLED: console_view waterfall_view grid_view
for i in base wsgi_dashboards codeparameter nestedexample; do
  pushd www/${i}
  yarn install
  py_install
  popd
done
