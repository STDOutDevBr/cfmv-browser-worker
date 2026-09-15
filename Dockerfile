# Imagem oficial do Playwright para Python: já traz o Chromium com as
# dependências de sistema, então não há `playwright install` aqui. A tag é
# fixada na mesma versão do pacote em pyproject.toml (playwright==1.62.0):
# as duas precisam bater, senão o Chromium da imagem não fala com o driver.
FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app

# Sem "[dev]": pytest e ruff não sobem para produção.
RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
