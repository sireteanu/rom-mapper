FROM alpine:3.20

RUN apk add --no-cache bash coreutils sed grep

COPY rom-mapper.sh /usr/local/bin/rom-mapper.sh
RUN chmod +x /usr/local/bin/rom-mapper.sh

ENTRYPOINT ["/usr/local/bin/rom-mapper.sh"]
