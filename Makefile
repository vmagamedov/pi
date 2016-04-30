__default__:
	@echo "Please specify a target to make"

begin:
	docker run -dt --name=app ubuntu:trusty

play:
	ansible-playbook -i inventory.txt playbook.yaml

clean:
	docker rm -f app
