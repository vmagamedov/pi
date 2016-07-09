PYTHON_VERSION=2.7.12
PYTHON_PREFIX=/.pi-python

apk add --update-cache \
  libc-dev linux-headers zlib-dev \
  gcc pax-utils make curl zip

curl -fSL "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-$PYTHON_VERSION.tar.xz" -o Python.tar.xz \
  && tar -xJf Python.tar.xz

cd "/Python-${PYTHON_VERSION}" \
  && cp /in/ModulesSetup.local ./Modules/Setup.local \
  && ./configure --prefix=$PYTHON_PREFIX --disable-shared LDFLAGS="-static" CFLAGS="-static" CPPFLAGS="-static" \
  && make \
  && make install || true

cd $PYTHON_PREFIX/lib/python2.7 \
  && rm -rf ./test \
  && rm -rf ./lib2to3/tests \
  && $PYTHON_PREFIX/bin/python2.7 -O -m compileall -f -q . \
  && find . -name "*.py" -type f -delete \
  && find . -name "*.pyc" -type f -delete \
  && zip -r $PYTHON_PREFIX/lib/python2.7.zip *

curl -fSL https://github.com/lalyos/docker-upx/releases/download/v3.91/upx -o /bin/upx \
  && chmod +x /bin/upx \
  && /bin/upx $PYTHON_PREFIX/bin/python2.7

cp $PYTHON_PREFIX/bin/python2.7 /out/python2.7
cp $PYTHON_PREFIX/lib/python2.7.zip /out/python27.zip
