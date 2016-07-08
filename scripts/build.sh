PYTHON_VERSION=2.7.12

apk add --update-cache \
  libc-dev linux-headers zlib-dev \
  gcc pax-utils make curl zip

curl -fSL "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-$PYTHON_VERSION.tar.xz" -o Python.tar.xz \
  && tar -xJf Python.tar.xz

cd "/Python-${PYTHON_VERSION}" \
  && cp /in/ModulesSetup.local ./Modules/Setup.local \
  && ./configure --prefix=/opt/python --disable-shared LDFLAGS="-static" CFLAGS="-static" CPPFLAGS="-static" \
  && make \
  && make install || echo 'ignore'

cd /opt/python/lib/python2.7 \
  && zip -r /opt/python/lib/python2.7.zip *

cp /opt/python/bin/python2.7 /out/_python
cp /opt/python/lib/python2.7.zip /out/stdlib.zip
