#!/bin/bash

set -e
set -x

# make sure we get the right version number
git fetch kdab --tags
git fetch origin --tags

# required for yarn
export PATH="$PATH:$PWD/node_modules/.bin/"
npm install yarn webpack-cli

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

pushd www/build_common
rm -rf node_modules
yarn install
popd

pushd www/
rm -rf node_modules
cp -r build_common/node_modules .
popd

pushd www/guanlecoja-ui/
rm -rf node_modules
yarn install
yarn build
popd

pushd www/data_module
rm -rf node_modules
yarn install
popd

# copied from Buildbot's Makefile, adapt as required
# DISABLED: console_view waterfall_view grid_view
for i in base wsgi_dashboards codeparameter nestedexample; do
  pushd www/${i}
  export PATH="$PATH:$PWD/node_modules/.bin/"
  rm -rf node_modules
  py_install
  popd
done
