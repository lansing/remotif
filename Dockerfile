FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl make gcc libc6-dev libpng-dev && \
    rm -rf /var/lib/apt/lists/*

# Build scale2x from source
RUN curl -sL https://github.com/amadvance/scale2x/releases/download/v4.0/scale2x-4.0.tar.gz | \
    tar xz && cd scale2x-4.0 && ./configure && make && make install && \
    cd / && rm -rf scale2x-4.0

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir pillow

COPY generate.py preview.py Makefile ./

RUN make fetch-assets

EXPOSE 8089
CMD ["python", "preview.py"]
