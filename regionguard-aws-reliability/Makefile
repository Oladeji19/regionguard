.PHONY: install test lint synth deploy destroy

install:
	python3 -m venv .venv
	. .venv/bin/activate && pip install -r requirements-dev.txt
	npm install

test:
	. .venv/bin/activate && pytest -q

lint:
	. .venv/bin/activate && ruff check .

synth:
	. .venv/bin/activate && npx cdk synth

deploy:
	. .venv/bin/activate && npx cdk deploy

destroy:
	. .venv/bin/activate && npx cdk destroy

