FROM python:3.12

WORKDIR /app

# Copy source
COPY . .

# Install deps
RUN pip install uv && uv sync --no-dev --no-cache

# Fix shebang
RUN sed -i '1 s|^#!.*python3$|#!/app/.venv/bin/python3|' /app/.venv/bin/silverback

# Ensure the project venv is on PATH so 'silverback' is found
ENV PATH="/app/.venv/bin:${PATH}"

# Default entrypoint, compose will pass rest of the args
ENTRYPOINT ["silverback"]