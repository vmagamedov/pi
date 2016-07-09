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
  && make install || true

cd /opt/python/lib/python2.7 \
  && rm -rf ./test \
  && rm -rf ./lib2to3/tests \
  && /opt/python/bin/python2.7 -O -m compileall -f -q . \
  && find . -name "*.py" -type f -delete \
  && find . -name "*.pyc" -type f -delete \
  && zip -r /opt/python/lib/python2.7.zip *

curl -fSL https://github.com/lalyos/docker-upx/releases/download/v3.91/upx -o /bin/upx \
  && chmod +x /bin/upx \
  && /bin/upx /opt/python/bin/python2.7

cp /opt/python/bin/python2.7 /out/_python
cp /opt/python/lib/python2.7.zip /out/stdlib.zip
