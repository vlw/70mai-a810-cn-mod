# Build environment: UBI/UBIFS tools (mtd-utils) and ubi_reader for unpacking.
FROM debian:bookworm
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends mtd-utils python3 python3-venv python3-dev gcc liblzo2-dev \
    ca-certificates unzip \
 && python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install -q ubi_reader==0.8.10 python-lzo==1.15 \
 && apt-get purge -y -qq gcc python3-dev && apt-get autoremove -y -qq && rm -rf /var/lib/apt/lists/*
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /src
