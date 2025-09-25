from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from datetime import datetime, timedelta
import time
import random
import os
import uuid
from functools import wraps
import re

app = Flask(__name__)

# Configuração básica
app.secret_key = os.environ.get('SECRET_KEY', 'minha-chave-super-secreta-123')
app.config['DEBUG'] = True

# Limites e configurações
MAX_NAME_LEN = 100
MIN_NAME_LEN = 2
MAX_DESC_LEN = 500

STATUS_OPTIONS = ['planning', 'in_progress', 'testing', 'completed', 'on_hold', 'cancelled']
PRIORITY_OPTIONS = ['low', 'medium', 'high', 'critical']

# Banco de dados simples em memória
projects = []
users = {
    'admin': {'password': 'admin123', 'name': 'Admin'},
    'user': {'password': 'user123', 'name': 'User'}
}

# Rate limiting simples
request_history = {}

@app.after_request
def add_cors_headers(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

def generate_id():
    return str(uuid.uuid4())

def is_valid_name(name):
    if not name or not name.strip():
        return False, "Nome é obrigatório"
    
    name = name.strip()
    if len(name) < MIN_NAME_LEN:
        return False, f"Nome muito curto (mínimo {MIN_NAME_LEN} caracteres)"
    
    if len(name) > MAX_NAME_LEN:
        return False, f"Nome muito longo (máximo {MAX_NAME_LEN} caracteres)"
    
    return True, ""

def is_valid_tags(tags):
    if len(tags) > 10:
        return False, "Máximo 10 tags"
    
    for tag in tags:
        if len(tag.strip()) > 20:
            return False, "Tag muito longa"
    
    return True, ""

def make_project(project_id, name, description="", status="planning", 
                priority="medium", tags=None, created_by=None):
    now = datetime.now()
    
    if created_by is None:
        try:
            created_by = session.get('username', 'anonimo')
        except:
            created_by = 'system'
    
    return {
        'id': project_id,
        'name': name,
        'description': description,
        'status': status,
        'priority': priority,
        'tags': tags or [],
        'progress': 0,
        'created_at': now.isoformat(),
        'updated_at': now.isoformat(),
        'created_by': created_by
    }

def login_required(f):
    @wraps(f)
    def check_login(*args, **kwargs):
        if 'username' not in session:
            return jsonify({'success': False, 'message': 'Faça login primeiro'}), 401
        return f(*args, **kwargs)
    return check_login

def check_rate_limit(f):
    @wraps(f)
    def limit_requests(*args, **kwargs):
        ip = request.remote_addr
        now = datetime.now()
        
        # Limpar histórico antigo
        minute_ago = now - timedelta(minutes=1)
        if ip in request_history:
            request_history[ip] = [t for t in request_history[ip] if t > minute_ago]
        
        # Verificar limite
        if ip in request_history and len(request_history[ip]) >= 60:
            return jsonify({'success': False, 'message': 'Muitas requisições'}), 429
        
        # Registrar requisição
        if ip not in request_history:
            request_history[ip] = []
        request_history[ip].append(now)
        
        return f(*args, **kwargs)
    return limit_requests

# Endpoints de autenticação
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')
    
    data = request.get_json() if request.is_json else request.form
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    if not username or not password:
        return jsonify({'success': False, 'message': 'Preencha todos os campos'}), 400
    
    user = users.get(username)
    if not user or user['password'] != password:
        return jsonify({'success': False, 'message': 'Usuário ou senha incorretos'}), 401
    
    session['username'] = username
    session['user_name'] = user['name']
    
    return jsonify({
        'success': True,
        'message': f'Olá, {user["name"]}!',
        'user': {'username': username, 'name': user['name']}
    })

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True, 'message': 'Até logo!'})

@app.route('/profile')
@login_required
def profile():
    username = session['username']
    user_projects = [p for p in projects if p['created_by'] == username]
    
    return jsonify({
        'success': True,
        'user': {
            'username': username,
            'name': session['user_name'],
            'projects_count': len(user_projects),
            'projects': user_projects
        }
    })

@app.route('/')
def index():
    """Página principal com o botão de criar projeto"""
    is_logged_in = 'username' in session
    return render_template('index.html', 
                         is_logged_in=is_logged_in,
                         username=session.get('user_name', ''))

@app.route('/create_project', methods=['POST'])
@login_required
@check_rate_limit
def create_project():
    data = request.get_json() if request.is_json else request.form
    
    name = data.get('name', '').strip()
    description = data.get('description', '').strip()
    status = data.get('status', 'planning').lower()
    priority = data.get('priority', 'medium').lower()
    tags = data.get('tags', [])
    
    # Processar tags
    if isinstance(tags, str):
        tags = [tag.strip() for tag in tags.split(',') if tag.strip()]
    
    # Validações
    valid, msg = is_valid_name(name)
    if not valid:
        return jsonify({'success': False, 'message': msg}), 400
    
    if description and len(description) > MAX_DESC_LEN:
        return jsonify({'success': False, 'message': 'Descrição muito longa'}), 400
    
    if status not in STATUS_OPTIONS:
        return jsonify({'success': False, 'message': 'Status inválido'}), 400
    
    if priority not in PRIORITY_OPTIONS:
        return jsonify({'success': False, 'message': 'Prioridade inválida'}), 400
    
    valid, msg = is_valid_tags(tags)
    if not valid:
        return jsonify({'success': False, 'message': msg}), 400
    
    # Verificar duplicatas
    if any(p['name'].lower() == name.lower() for p in projects):
        return jsonify({'success': False, 'message': 'Já existe projeto com esse nome'}), 409
    
    # Simular erro ocasional
    if random.random() < 0.05:
        return jsonify({'success': False, 'message': 'Ops, algo deu errado. Tente de novo'}), 500
    
    # Criar projeto
    project = make_project(
        project_id=generate_id(),
        name=name,
        description=description,
        status=status,
        priority=priority,
        tags=tags
    )
    
    projects.append(project)
    
    return jsonify({
        'success': True,
        'message': 'Projeto criado!',
        'project': project
    }), 201

@app.route('/projects', methods=['GET'])
@login_required
def list_projects():
    search = request.args.get('search', '').lower()
    status_filter = request.args.get('status', '').lower()
    priority_filter = request.args.get('priority', '').lower()
    
    filtered = projects
    
    if search:
        filtered = [p for p in filtered if search in p['name'].lower() or search in p['description'].lower()]
    
    if status_filter and status_filter in STATUS_OPTIONS:
        filtered = [p for p in filtered if p['status'] == status_filter]
    
    if priority_filter and priority_filter in PRIORITY_OPTIONS:
        filtered = [p for p in filtered if p['priority'] == priority_filter]
    
    return jsonify({'success': True, 'projects': filtered, 'total': len(filtered)})

@app.route('/projects/<project_id>', methods=['GET'])
@login_required
def get_project(project_id):
    project = next((p for p in projects if p['id'] == project_id), None)
    if not project:
        return jsonify({'success': False, 'message': 'Projeto não encontrado'}), 404
    
    return jsonify({'success': True, 'project': project})

@app.route('/projects/<project_id>', methods=['PUT'])
@login_required
@check_rate_limit
def update_project(project_id):
    project = next((p for p in projects if p['id'] == project_id), None)
    if not project:
        return jsonify({'success': False, 'message': 'Projeto não encontrado'}), 404
    
    if project['created_by'] != session['username']:
        return jsonify({'success': False, 'message': 'Sem permissão'}), 403
    
    data = request.get_json() if request.is_json else request.form
    
    if 'name' in data:
        new_name = data['name'].strip()
        valid, msg = is_valid_name(new_name)
        if not valid:
            return jsonify({'success': False, 'message': msg}), 400
        
        if any(p['name'].lower() == new_name.lower() and p['id'] != project_id for p in projects):
            return jsonify({'success': False, 'message': 'Nome já existe'}), 409
        
        project['name'] = new_name
    
    if 'description' in data:
        desc = data['description'].strip()
        if len(desc) > MAX_DESC_LEN:
            return jsonify({'success': False, 'message': 'Descrição muito longa'}), 400
        project['description'] = desc
    
    if 'status' in data:
        status = data['status'].lower()
        if status not in STATUS_OPTIONS:
            return jsonify({'success': False, 'message': 'Status inválido'}), 400
        project['status'] = status
    
    if 'priority' in data:
        priority = data['priority'].lower()
        if priority not in PRIORITY_OPTIONS:
            return jsonify({'success': False, 'message': 'Prioridade inválida'}), 400
        project['priority'] = priority
    
    if 'progress' in data:
        progress = int(data['progress'])
        if not 0 <= progress <= 100:
            return jsonify({'success': False, 'message': 'Progresso deve ser 0-100'}), 400
        project['progress'] = progress
    
    if 'tags' in data:
        tags = data['tags']
        if isinstance(tags, str):
            tags = [tag.strip() for tag in tags.split(',') if tag.strip()]
        
        valid, msg = is_valid_tags(tags)
        if not valid:
            return jsonify({'success': False, 'message': msg}), 400
        
        project['tags'] = tags
    
    project['updated_at'] = datetime.now().isoformat()
    
    return jsonify({'success': True, 'message': 'Projeto atualizado!', 'project': project})

@app.route('/projects/<project_id>', methods=['DELETE'])
@login_required
def delete_project(project_id):
    project = next((p for p in projects if p['id'] == project_id), None)
    if not project:
        return jsonify({'success': False, 'message': 'Projeto não encontrado'}), 404
    
    if project['created_by'] != session['username']:
        return jsonify({'success': False, 'message': 'Sem permissão'}), 403
    
    projects.remove(project)
    return jsonify({'success': True, 'message': 'Projeto deletado!'})

@app.route('/project/<project_id>/config')
@login_required
def project_config(project_id):
    project = next((p for p in projects if p['id'] == project_id), None)
    if not project:
        return redirect(url_for('index'))
    
    return render_template('project_config.html', 
                         project=project,
                         allowed_statuses=STATUS_OPTIONS,
                         allowed_priorities=PRIORITY_OPTIONS)

# Estatísticas
@app.route('/stats', methods=['GET'])
@login_required
def get_stats():
    user_projects = [p for p in projects if p['created_by'] == session['username']]
    
    status_stats = {}
    for status in STATUS_OPTIONS:
        status_stats[status] = len([p for p in user_projects if p['status'] == status])
    
    priority_stats = {}
    for priority in PRIORITY_OPTIONS:
        priority_stats[priority] = len([p for p in user_projects if p['priority'] == priority])
    
    avg_progress = sum(p['progress'] for p in user_projects) / len(user_projects) if user_projects else 0
    
    return jsonify({
        'success': True,
        'stats': {
            'total_projects': len(projects),
            'user_projects': len(user_projects),
            'status_distribution': status_stats,
            'priority_distribution': priority_stats,
            'average_progress': round(avg_progress, 2)
        }
    })

# Handlers de erro personalizados
@app.errorhandler(404)
def not_found_error(error):
    """Handler para erro 404"""
    return jsonify({
        'success': False,
        'message': 'Recurso não encontrado',
        'error_code': 404
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        'success': False,
        'message': 'Erro interno do servidor',
        'error_code': 500
    }), 500

@app.errorhandler(403)
def forbidden_error(error):
    """Handler para erro 403"""
    return jsonify({
        'success': False,
        'message': 'Acesso negado',
        'error_code': 403
    }), 403

@app.errorhandler(400)
def bad_request_error(error):
    """Handler para erro 400"""
    return jsonify({
        'success': False,
        'message': 'Requisição inválida',
        'error_code': 400
    }), 400

@app.before_request
def log_request_info():
    pass

# Removido - já está integrado no after_request_cors

# Endpoint de saúde da aplicação
@app.route('/health')
def health_check():
    """Verificação de saúde da aplicação"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': '2.0.0',
        'projects_count': len(projects),
        'users_count': len(users)
    })

if __name__ == '__main__':
    # Projetos de exemplo
    if not projects:
        example_projects = [
            make_project(
                project_id=generate_id(),
                name="Projeto de Exemplo 1",
                description="Este é um projeto de demonstração",
                status="in_progress",
                priority="high",
                tags=["exemplo", "demo"],
                created_by="admin"
            ),
            make_project(
                project_id=generate_id(),
                name="Projeto de Exemplo 2", 
                description="Outro projeto para teste",
                status="planning",
                priority="medium",
                tags=["teste", "planejamento"],
                created_by="admin"
            )
        ]
        projects.extend(example_projects)
    
    app.run(debug=True, host='127.0.0.1', port=5000)