FROM alpine:3.21

RUN apk add --no-cache pgbouncer netcat-openbsd

COPY ./compose/production/pgbouncer/entrypoint /entrypoint
RUN sed -i 's/\r$//g' /entrypoint \
    && chmod +x /entrypoint

ENTRYPOINT ["/entrypoint"]
