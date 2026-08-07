# FlowSpace — Gestão de Projetos

Clone profissional do Asana em Django com Kanban animado, Timeline e design moderno.

## Instalação

```bash
cd flowspace
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py seed_data
python manage.py runserver
```

Acesse: **http://127.0.0.1:8000**

> `DEBUG` agora é `False` por padrão (para nunca vazar stack traces/segredos caso
> um deploy esqueça de configurar as variáveis de ambiente). O arquivo `.env`
> (criado a partir do `.env.example`, nunca versionado) já vem com `DEBUG=True`
> para desenvolvimento local — o Django carrega ele automaticamente, sem precisar
> exportar nada manualmente no terminal. Em produção, defina `DEBUG=False`
> (ou omita a linha do `.env`) e configure `SECRET_KEY` com um valor único e
> secreto — a aplicação recusa iniciar sem isso.

| Usuário | Senha | Função |
|---|---|---|
| admin | admin123 | Proprietário |
| edcarlos | admin123 | Admin / PM |
| maria | admin123 | Designer |
| joao | admin123 | Desenvolvedor |
| ana | admin123 | Marketing |

## Funcionalidades

- **Dashboard** com métricas, Timeline visual de projetos e tarefas prioritárias
- **Kanban Board** com drag-and-drop animado, cards com progresso e subtarefas
- **Vista Lista** e **Vista Timeline** por projeto
- **Tarefas** com subtarefas, comentários, responsáveis, prioridade, prazo e progresso
- **Projetos** com colunas customizáveis, cores e membros
- **Equipe** com controle de funções (owner, admin, manager, member, guest)
- **Perfil** com avatar colorido e cargo
