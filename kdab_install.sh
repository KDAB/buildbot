#!/bin/bash

function py_install() {
  python setup.py build || exit 1
  python setup.py install --prefix=~/opt || exit 1
}

cd master/
py_install
cd ../

pip install --prefix=~/opt -e pkg || exit 1
pip install --prefix=~/opt mock || exit 1

pushd www/data_module
npm install
node_modules/.bin/gulp prod --no-tests
popd

# copied from Buildbot's Makefile, adapt as required
for i in base wsgi_dashboards codeparameter console_view waterfall_view grid_view nestedexample; do
  cd www/${i}
  py_install
  cd ../..
done