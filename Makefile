install:
	python -m venv .venv
	.venv\Scripts\activate && pip install --upgrade pip && pip install -r requirements.txt

migrate:
	.venv\Scripts\activate && alembic upgrade head

run:
	.venv\Scripts\activate && uvicorn app.main:app --host 0.0.0.0 --port 8000

docker-build:
	docker build -t ai-leads-tracker .

docker-up:
	docker-compose up --build

docker-migrate:
	docker-compose run --rm web alembic upgrade head
