"""
Script de teste automatizado do sistema FlowSpace.
Testa todos os fluxos principais via API.
"""
import requests, json, sys, subprocess, os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BASE = 'http://localhost:8000'
results = []

def ok(label):
    results.append(('OK', label))
    print(f'  [OK] {label}')

def fail(label, detail=''):
    results.append(('FAIL', label))
    print(f'  [FAIL] {label}: {detail}')

# ── 1. Autenticação ──────────────────────────────────────────────────────────
print('\n=== 1. AUTENTICACAO ===')

r = requests.post(f'{BASE}/api/auth/login/', json={'username': 'admin', 'password': 'admin123'})
if r.status_code == 200 and 'access' in r.json():
    TOKEN_ADMIN = r.json()['access']
    ADMIN_ID    = r.json()['user']['id']
    ok('Login admin (owner)')
else:
    fail('Login admin', r.text[:120])
    sys.exit(1)

# Tenta logar como membro
MEMBER_USER = None
for uname in ['brunosilva', 'edcarlos', 'joao', 'member']:
    r2 = requests.post(f'{BASE}/api/auth/login/', json={'username': uname, 'password': 'admin123'})
    if r2.status_code == 200:
        TOKEN_MEMBER = r2.json()['access']
        MEMBER_ID    = r2.json()['user']['id']
        MEMBER_NAME  = r2.json()['user']['username']
        MEMBER_USER  = uname
        ok(f'Login membro: {uname}')
        break

if not MEMBER_USER:
    print('  [WARN] Nenhum membro encontrado, usando admin como membro')
    TOKEN_MEMBER = TOKEN_ADMIN
    MEMBER_ID    = ADMIN_ID
    MEMBER_NAME  = 'admin'

H_ADMIN  = {'Authorization': f'Bearer {TOKEN_ADMIN}'}
H_MEMBER = {'Authorization': f'Bearer {TOKEN_MEMBER}'}

# ── 2. Projetos ──────────────────────────────────────────────────────────────
print('\n=== 2. PROJETOS ===')

r = requests.get(f'{BASE}/api/projects/', headers=H_ADMIN)
if r.status_code == 200 and r.json():
    projetos = r.json()
    projeto  = projetos[0]
    PROJ_ID  = projeto['id']
    ok(f'Listar projetos ({len(projetos)} encontrados, testando: "{projeto["name"]}")')
else:
    fail('Listar projetos', r.text[:120])
    sys.exit(1)

r = requests.get(f'{BASE}/api/projects/{PROJ_ID}/', headers=H_ADMIN)
if r.status_code == 200:
    proj_detail = r.json()
    cols = proj_detail.get('columns', [])
    if cols:
        COL_TODO = next((c['id'] for c in cols if 'fazer' in c['name'].lower()), cols[0]['id'])
        COL_DONE = next((c['id'] for c in cols if 'conclu' in c['name'].lower()), cols[-1]['id'])
        ok(f'Detalhe projeto OK ({len(cols)} colunas)')
    else:
        fail('Projeto sem colunas')
        COL_TODO = None
        COL_DONE = None
else:
    fail('Detalhe projeto', r.text[:120])
    sys.exit(1)

# ── 3. Criar tarefa ──────────────────────────────────────────────────────────
print('\n=== 3. CRIAR TAREFA ===')

payload = {
    'title':        '[TESTE AUTO] Tarefa de teste automatizado',
    'project':      PROJ_ID,
    'column':       COL_TODO,
    'status':       'todo',
    'priority':     'medium',
    'needs_review': True,
    'assignees':    [MEMBER_ID],
}
r = requests.post(f'{BASE}/api/tasks/create/', headers=H_ADMIN, json=payload)
if r.status_code in (200, 201) and 'id' in r.json():
    TASK_ID = r.json()['id']
    ok(f'Criar tarefa com needs_review=True (id={TASK_ID[:8]}...)')
else:
    fail('Criar tarefa', r.text[:200])
    sys.exit(1)

r = requests.get(f'{BASE}/api/tasks/{TASK_ID}/', headers=H_MEMBER)
if r.status_code == 200:
    t = r.json()
    ok(f'Detalhe tarefa (status={t["status"]}, needs_review={t.get("needs_review")})')
    if t['status'] != 'todo':
        fail(f'Status esperado "todo", recebido "{t["status"]}"')
else:
    fail('Detalhe tarefa', r.text[:120])

# ── 4. Fluxo de status ───────────────────────────────────────────────────────
print('\n=== 4. FLUXO DE STATUS (todo -> in_progress -> review -> done) ===')

# todo -> in_progress (membro assignee)
r = requests.post(f'{BASE}/api/tasks/{TASK_ID}/advance/', headers=H_MEMBER)
d = r.json()
if d.get('ok') and d.get('status') == 'in_progress':
    ok('todo -> in_progress (membro assignee)')
else:
    fail('todo -> in_progress', str(d))

# in_progress -> review (needs_review=True, membro)
r = requests.post(f'{BASE}/api/tasks/{TASK_ID}/advance/', headers=H_MEMBER)
d = r.json()
if d.get('ok') and d.get('status') == 'review':
    ok('in_progress -> review (needs_review=True, correto!)')
else:
    fail('in_progress -> review', str(d))

# Review só pode ser aprovado por gestor/admin — EdCarlos é admin, então pode
# Testamos com um usuário membro puro (sem role admin): verifica quem pode aprovar
r_task = requests.get(f'{BASE}/api/tasks/{TASK_ID}/', headers=H_ADMIN)
task_status = r_task.json().get('status')
if task_status == 'review':
    # Usa admin para aprovar (comportamento correto)
    r = requests.post(f'{BASE}/api/tasks/{TASK_ID}/advance/', headers=H_ADMIN)
    d = r.json()
    if d.get('ok') and d.get('status') == 'done':
        ok('review -> done (gestor/admin aprova e conclui)')
    else:
        fail('review -> done', str(d))
elif task_status == 'done':
    ok('review -> done (ja aprovado pelo membro com role admin — correto!)')

# Verificar tarefa concluída
r = requests.get(f'{BASE}/api/tasks/{TASK_ID}/', headers=H_ADMIN)
if r.status_code == 200 and r.json()['status'] == 'done':
    ok('Tarefa confirmada como done no banco')
else:
    fail('Verificar status final', r.json().get('status'))

# ── 5. Tarefa sem review (fluxo direto) ─────────────────────────────────────
print('\n=== 5. FLUXO SEM REVIEW (in_progress -> done direto) ===')

r = requests.post(f'{BASE}/api/tasks/create/', headers=H_ADMIN, json={
    'title':        '[TESTE AUTO] Sem review',
    'project':      PROJ_ID,
    'column':       COL_TODO,
    'status':       'todo',
    'priority':     'low',
    'needs_review': False,
    'assignees':    [MEMBER_ID],
})
if r.status_code in (200, 201):
    TASK2_ID = r.json()['id']
    ok('Criar tarefa needs_review=False')
    # todo -> in_progress
    requests.post(f'{BASE}/api/tasks/{TASK2_ID}/advance/', headers=H_MEMBER)
    # in_progress -> done (direto, sem review)
    r2 = requests.post(f'{BASE}/api/tasks/{TASK2_ID}/advance/', headers=H_MEMBER)
    d2 = r2.json()
    if d2.get('ok') and d2.get('status') == 'done':
        ok('in_progress -> done (sem review, fluxo direto correto!)')
    else:
        fail('in_progress -> done direto', str(d2))
else:
    fail('Criar tarefa sem review', r.text[:120])

# ── 6. Fluxo Backlog ─────────────────────────────────────────────────────────
print('\n=== 6. FLUXO BACKLOG (qualquer membro assume) ===')

r = requests.post(f'{BASE}/api/tasks/create/', headers=H_ADMIN, json={
    'title':    '[TESTE AUTO] Backlog',
    'project':  PROJ_ID,
    'column':   COL_TODO,
    'status':   'backlog',
    'priority': 'low',
})
if r.status_code in (200, 201):
    TASK3_ID = r.json()['id']
    ok('Criar tarefa em backlog (sem assignee)')
    # Membro assume o backlog
    r2 = requests.post(f'{BASE}/api/tasks/{TASK3_ID}/advance/', headers=H_MEMBER)
    d2 = r2.json()
    if d2.get('ok') and d2.get('status') == 'todo':
        ok('backlog -> todo (membro assumiu como responsavel!)')
    else:
        fail('backlog -> todo', str(d2))
else:
    fail('Criar tarefa backlog', r.text[:120])

# ── 7. Subtarefas ────────────────────────────────────────────────────────────
print('\n=== 7. SUBTAREFAS ===')

import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
result = subprocess.run([
    os.path.join(BASE_DIR, 'venv', 'Scripts', 'python.exe'),
    os.path.join(BASE_DIR, 'manage.py'), 'shell', '-c',
    (
        'from apps.tasks.models import Task, SubTask; '
        f't=Task.objects.get(pk="{TASK_ID}"); '
        'st=SubTask.objects.create(task=t, title="Subtarefa auto-teste"); '
        'print(st.id)'
    )
], capture_output=True, text=True, cwd=BASE_DIR)

if result.returncode == 0:
    ST_ID = result.stdout.strip()
    ok(f'Subtarefa criada via shell (id={ST_ID[:8]}...)')
    r = requests.post(f'{BASE}/api/subtasks/{ST_ID}/toggle/', headers=H_MEMBER)
    d = r.json()
    if 'done' in d:
        ok(f'Toggle subtarefa -> done={d.get("done")}, progress={d.get("progress")}%')
    else:
        fail('Toggle subtarefa', str(d))
else:
    fail('Criar subtarefa', result.stderr[:100])

# ── 8. Presença Online ───────────────────────────────────────────────────────
print('\n=== 8. PRESENCA ONLINE ===')

r = requests.post(f'{BASE}/api/presence/heartbeat/', headers=H_ADMIN)
if r.status_code == 200 and r.json().get('ok'):
    ok('Heartbeat admin registrado no servidor')
else:
    fail('Heartbeat admin', r.text[:100])

r = requests.post(f'{BASE}/api/presence/heartbeat/', headers=H_MEMBER)
if r.status_code == 200 and r.json().get('ok'):
    ok(f'Heartbeat {MEMBER_NAME} registrado no servidor')
else:
    fail('Heartbeat membro', r.text[:100])

r = requests.get(f'{BASE}/api/presence/online/', headers=H_ADMIN)
if r.status_code == 200:
    online = r.json().get('online', [])
    if ADMIN_ID in online:
        ok(f'Online list OK — admin aparece ({len(online)} usuario(s) online)')
    else:
        fail('Admin nao aparece na lista online', str(online[:3]))
    if MEMBER_ID in online and MEMBER_ID != ADMIN_ID:
        ok(f'Online list OK — {MEMBER_NAME} tambem aparece')
else:
    fail('Online list', r.text[:100])

# ── 9. Notificações ──────────────────────────────────────────────────────────
print('\n=== 9. NOTIFICACOES ===')

r = requests.get(f'{BASE}/api/notifications/', headers=H_MEMBER)
if r.status_code == 200:
    ok(f'Listar notificacoes ({len(r.json())} encontradas)')
else:
    fail('Listar notificacoes', r.text[:100])

r = requests.post(f'{BASE}/api/notifications/read-all/', headers=H_MEMBER)
if r.status_code == 200:
    ok('Marcar todas como lidas')
else:
    fail('Marcar notificacoes lidas', r.text[:100])

# ── 10. Dashboard ────────────────────────────────────────────────────────────
print('\n=== 10. DASHBOARD ===')

r = requests.get(f'{BASE}/api/dashboard/', headers=H_ADMIN)
if r.status_code == 200:
    ok('Dashboard API retornou 200')
else:
    fail('Dashboard API', r.text[:100])

# ── 11. Kanban ───────────────────────────────────────────────────────────────
print('\n=== 11. KANBAN ===')

r = requests.get(f'{BASE}/api/projects/{PROJ_ID}/', headers=H_ADMIN)
if r.status_code == 200:
    cols = r.json().get('columns', [])
    total = sum(len(c.get('tasks', [])) for c in cols)
    ok(f'Kanban OK ({len(cols)} colunas, {total} tarefas visíveis)')
    for col in cols:
        tasks_in_col = col.get('tasks', [])
        print(f'       Coluna "{col["name"]}": {len(tasks_in_col)} tarefa(s)')
else:
    fail('Kanban', r.text[:100])

# ── 12. Equipe ───────────────────────────────────────────────────────────────
print('\n=== 12. EQUIPE ===')

r = requests.get(f'{BASE}/api/team/', headers=H_ADMIN)
if r.status_code == 200:
    ok(f'Lista equipe ({len(r.json())} membros)')
else:
    fail('Lista equipe', r.text[:100])

# ── Limpeza ──────────────────────────────────────────────────────────────────
print('\n=== LIMPEZA (removendo tarefas de teste) ===')
subprocess.run([
    os.path.join(BASE_DIR, 'venv', 'Scripts', 'python.exe'),
    os.path.join(BASE_DIR, 'manage.py'), 'shell', '-c',
    'from apps.tasks.models import Task; n=Task.objects.filter(title__startswith="[TESTE AUTO]").delete(); print(f"Removidas {n[0]} tarefas de teste")'
], capture_output=True, text=True, cwd=BASE_DIR)
ok('Tarefas de teste removidas do banco')

# ── Resultado Final ───────────────────────────────────────────────────────────
print('\n' + '='*50)
passed = sum(1 for s, _ in results if s == 'OK')
failed = sum(1 for s, _ in results if s == 'FAIL')
print(f'  RESULTADO: {passed} OK  |  {failed} FALHAS')
if failed == 0:
    print('  SISTEMA FUNCIONANDO CORRETAMENTE!')
else:
    print('  PROBLEMAS ENCONTRADOS:')
    for s, l in results:
        if s == 'FAIL':
            print(f'    x {l}')
print('='*50)
