# Configuration

## `!Meta`

{% method %}
Project-specific settings.

- `namespace` of type `str` - name, used to namespace such things like network,
  to make them unique and isolated for every project;
- `description` of type `str` - description for a project, which will be seen
  when users will run `pi --help` command.

{% sample lang="yaml" %}
```yaml
- !Meta:
  namespace: envoy
  description: |
    This project
```
{% endmethod %}

## `!Image`

{% method %}
Defines how to build and distribute an image.

- `name` of type `str` - short name of the image, used to reference it within this
  config/project;
- `repository` of type `str` - full name of the image. This name is used to distribute
  image using registries;
- `from` of type `str` or `!DockerImage` - base image, to build this one from. It is
  a name of the other image defined in this config, or a regular external
  Docker image;
- `description` of type `str` - description of this image;
- `tasks` is a `list` of tasks, used to build this image.

{% sample lang="yaml" %}
```yaml
- !Image:
  name: env
  repository: my.registry/project/name
  from: base
  description: "Project environment"
  tasks:
  - run: cp {{config}} /etc
    config: !File "config.py"
```
{% endmethod %}

#### Tasks

Each task represents a shell command to run. This command can be a simple string:

```yaml
  tasks:
  - run: mkdir /etc/app
```

or a template with parameters. Jinja2 is used as a template language:

```yaml
  tasks:
  - run: pip install {{packages|join(" ")}}
    packages:
    - flask
    - sqlalchemy
```

You can also use some special handy directives:

```yaml
  tasks:
  - run: sh -c {{install_sh}}
    install_sh: !Download "https://some.host/install.sh"
```

`Pi` will download this file for you and it will be available inside container
during build process. All you need it to describe what you want to do with
already downloaded file. So you don't have to install curl with ca-certificates
into container and remove it in the end.

### `!DockerImage`

{% method %}
Reference to a name of the Docker image. Takes single argument of `str` type - image name.
Image name should include repository name and tag.

{% sample lang="yaml" %}
```yaml
- !Image:
  name: base
  from: !DockerImage "python:3.6-alpine"
  {...}
```
{% endmethod %}

### `!File`

{% method %}
Directive to transfer file from the host machine into container.
Takes single argument of `str` type - local file path.

{% sample lang="yaml" %}
```yaml
  tasks:
  - run: cp {{config}} /etc/config.yaml
    config: !File "config.yaml"
```
{% endmethod %}

### `!Bundle`

{% method %}
Directive to transfer directory from the host machine into container.
Takes single argument of `str` type - local directory path.

{% sample lang="yaml" %}
```yaml
  tasks:
  - run: cd {{src}} && python setup.py install
    src: !Bundle "src"
```
{% endmethod %}

### `!Download`

{% method %}
Directive to transfer downloaded on the host machine file into container.
Takes single argument of `str` type - url.

{% sample lang="yaml" %}
```yaml
  tasks:
  - run: sh -c {{install_sh}}
    install_sh: !Download "https://some.host/install.sh"
```
{% endmethod %}

## `!Command`

{% method %}
Defines a command with parameters, to run inside configured container and environment.

- `name` of type `str` - name of this command;
- `image` of type `str` or `!DockerImage` - image, used to run this command;
- `run` of type `str` - command to run inside container;
- `params` is a `list` of command-line options of type `!Option` and/or arguments of type`!Argument`;
- `volumes` is a `list` of volumes of type `!Volume` to mount;
- `ports` is a `list` of directives of type `!Expose`, used to expose ports from the container;
- `environ` is a `map` of environment variables;
- `requires` is a `list` of service names of type `str` - `pi` will ensure that these services are running;
- `network-name` of type `str` - host name of the container, seen by other containers in the project's namespace;
- `description` of type `str` - description, used to help users, when they run `pi [name] --help` command.

{% sample lang="yaml" %}
```yaml
- !Command
  name: test
  image: base
  params:
  - !Argument {name: tests, default: "tests"}
  run: py.test {{tests}}
```
{% endmethod %}

#### Defaults

#### Structure

#### Parameters

#### Network

### `!Option`
### `!Argument`
### `!Volume`
### `!Expose`
