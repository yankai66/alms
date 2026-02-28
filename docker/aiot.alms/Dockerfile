FROM 192.168.12.237:5000/bitnami/git:2.34.1-debian-10-r13 as giter
ADD . /code/
RUN cd /code/ && \
    git describe --tags --always --dirty="-dirty"  | awk '{print "tag: "$0}' > /code/version.txt && \
    git rev-parse HEAD | awk '{print "HEAD: "$0}' >> /code/version.txt  && \
    echo $(date +"%F%n%T %Z(%z)")| awk '{print "DATE: "$0}'  >> /code/version.txt


#FROM 192.168.12.237:5000/python:3.13.5-slim
#FROM 192.168.12.237:5000/python:3.12.7-bookworm
FROM harbor.sihua.tech/test_images/aiot.alms:basic

RUN rm -rf /opt/aiot/alms

RUN mkdir -p /opt/aiot/alms

WORKDIR /opt/aiot/alms

# Configure pip to use Alibaba Cloud mirror for faster installations in China
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV PIP_TRUSTED_HOST=mirrors.aliyun.com

# Copy and install Python dependencies first (better cache)
COPY ./requirements.txt /opt/aiot/alms/requirements.txt
RUN pip install --no-cache-dir -r /opt/aiot/alms/requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# Copy project
COPY .. /opt/aiot/alms

COPY --from=giter /code/version.txt /opt/aiot/alms/

# Ensure upload root exists (mounted in compose as volume)
RUN mkdir -p /data/uploads

# clean APT cache
RUN apt-get clean && rm -rf /var/lib/apt/lists/*

# Use project root so StaticFiles(directory="app/static") resolves
WORKDIR /opt/aiot/alms

EXPOSE 8088

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088", "--workers", "1"]


