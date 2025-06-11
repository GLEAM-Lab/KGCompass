# Use the official Neo4j 4.4.39 Community Edition image as the base
FROM neo4j:4.4.39-community

# Switch to root user to install curl
USER root
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
# Switch back to the default neo4j user
USER neo4j

# Set the password for the neo4j user
ENV NEO4J_AUTH=neo4j/neo4jpassword

# Use the official plugin mechanism to automatically download and install
# APOC and Graph Data Science plugins on the first run.
# The image's entrypoint script will handle the download of compatible versions.
ENV NEO4J_PLUGINS='["apoc", "graph-data-science"]'

# Expose the default Neo4j ports
EXPOSE 7474 7687 