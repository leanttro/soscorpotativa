import os
from datetime import datetime
from functools import wraps

from dotenv import load_dotenv
load_dotenv()  # em produção (Docker) as variáveis já vêm do ambiente; isso só afeta rodar local

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, flash, abort
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from slugify import slugify

# ─────────────────────────────────────────────
# CONFIGURAÇÃO
# ─────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "eventos-secret-key-2025")
# ^ precisa ser IGUAL à secret_key do app da Oficina (app_oficina.py), pois
#   é isso que faz os dois lerem a MESMA sessão (mesmo cookie). Em produção,
#   defina a env var SECRET_KEY uma vez só e os dois apps já compartilham.

# String de conexão PostgreSQL.
# Exemplo local: postgresql://usuario:senha@localhost:5432/soscorporativa
# Em produção (Render/Railway/Heroku) normalmente vem pronta em DATABASE_URL.
db_url = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/soscorporativa"
)
# Alguns provedores (Heroku antigo) mandam "postgres://" — o SQLAlchemy exige "postgresql://"
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# Dados fixos da "loja" (empresa) — substitui o multi-tenant do template original
LOJA = {
    "nome": "SOS Corporativa",
    "slug_url": "sos-corporativa",
}


# ─────────────────────────────────────────────
# MODELOS
# ─────────────────────────────────────────────
class Produto(db.Model):
    __tablename__ = "sos_produtos"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(220), unique=True, nullable=False)
    descricao = db.Column(db.Text)
    descricao_completa = db.Column(db.Text)
    imagem = db.Column(db.String(500))  # URL da imagem (ex: Cloudinary)
    ativo = db.Column(db.Boolean, default=True)
    ordem = db.Column(db.Integer, default=0)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Produto {self.nome}>"


class Post(db.Model):
    __tablename__ = "sos_posts"

    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(220), unique=True, nullable=False)
    resumo = db.Column(db.Text)
    conteudo = db.Column(db.Text)  # HTML ou markdown simples
    capa = db.Column(db.String(500))
    categoria = db.Column(db.String(80))
    data = db.Column(db.String(40))  # texto livre tipo "12 Ago 2026"
    publicado = db.Column(db.Boolean, default=True)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Post {self.titulo}>"


class Lead(db.Model):
    __tablename__ = "sos_leads"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), nullable=False)
    empresa = db.Column(db.String(200))
    email = db.Column(db.String(200), nullable=False)
    whatsapp = db.Column(db.String(40))
    servico = db.Column(db.String(120))
    mensagem = db.Column(db.Text)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Lead {self.nome}>"


# AdminUser / sos_admin_users NÃO é mais usado para login (o login agora é
# único, feito pelo app da Oficina — ver login_obrigatorio abaixo).
# A classe e a tabela ficam aqui só por compatibilidade; nada as apaga.
class AdminUser(db.Model):
    __tablename__ = "sos_admin_users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), unique=True, nullable=False)
    senha_hash = db.Column(db.String(300), nullable=False)

    def set_senha(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def checar_senha(self, senha):
        return check_password_hash(self.senha_hash, senha)


# ─────────────────────────────────────────────
# AUTENTICAÇÃO DO ADMIN
# ─────────────────────────────────────────────
# Login ÚNICO: não existe mais /admin/login próprio do SOS. Quem autentica
# é o app da Oficina (session['admin_id']). Aqui só CONFERIMOS se essa
# sessão já existe; se não existir, manda pro login da Oficina.
def login_obrigatorio(f):
    @wraps(f)
    def decorada(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect("/admin/login")
        return f(*args, **kwargs)
    return decorada


# ─────────────────────────────────────────────
# ROTAS PÚBLICAS — SITE
# ─────────────────────────────────────────────
@app.route("/")
def index():
    produtos = (
        Produto.query.filter_by(ativo=True)
        .order_by(Produto.ordem.asc(), Produto.criado_em.desc())
        .all()
    )
    posts = (
        Post.query.filter_by(publicado=True)
        .order_by(Post.criado_em.desc())
        .limit(9)
        .all()
    )
    return render_template(
        "index.html",
        loja=LOJA,
        produtos=produtos,
        posts=posts,
        directus_url="",  # não usado nesta versão
    )


@app.route("/<slug_loja>/produto/<slug>")
def produto_detalhe(slug_loja, slug):
    produto = Produto.query.filter_by(slug=slug, ativo=True).first_or_404()
    return render_template("produto_detalhe.html", loja=LOJA, produto=produto)


@app.route("/<slug_loja>/blog/<slug>")
def post_detalhe(slug_loja, slug):
    post = Post.query.filter_by(slug=slug, publicado=True).first_or_404()
    return render_template("post_detalhe.html", loja=LOJA, post=post)


@app.route("/<slug_loja>/captura-lead", methods=["POST"])
def captura_lead(slug_loja):
    try:
        nome = request.form.get("nome", "").strip()
        email = request.form.get("email", "").strip()

        if not nome or not email:
            return jsonify({"sucesso": False, "erro": "Nome e e-mail são obrigatórios."}), 400

        lead = Lead(
            nome=nome,
            empresa=request.form.get("empresa", "").strip(),
            email=email,
            whatsapp=request.form.get("whatsapp", "").strip(),
            servico=request.form.get("servico", "").strip(),
            mensagem=request.form.get("mensagem", "").strip(),
        )
        db.session.add(lead)
        db.session.commit()
        return jsonify({"sucesso": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"sucesso": False, "erro": str(e)}), 500


# ─────────────────────────────────────────────
# ADMIN: NÃO EXISTE MAIS AQUI DENTRO.
# ─────────────────────────────────────────────
# Não tem mais /admin, /admin/produtos, /admin/posts, /admin/leads,
# login, logout, nada disso neste app. Só existe UM admin — o da
# Oficina (app_oficina.py). Se algum dia precisar gerenciar produtos,
# posts ou leads do SOS por uma tela, essas telas/rotas devem ser
# criadas DENTRO do app_oficina.py, usando os mesmos modelos
# (Produto, Post, Lead) importados deste arquivo — não recriando
# um segundo admin aqui.
#
# As tabelas sos_produtos / sos_posts / sos_leads / sos_admin_users
# continuam existindo no banco, intocadas. sos_admin_users só ficou
# sem uso (não apagamos a tabela nem os dados).


# ─────────────────────────────────────────────
# COMANDO CLI PARA CRIAR TABELAS
# ─────────────────────────────────────────────
@app.cli.command("init-db")
def init_db():
    """Cria todas as tabelas no banco. Rode com: flask --app app.py init-db"""
    db.create_all()
    print("✅ Tabelas criadas com sucesso.")


if __name__ == "__main__":
    app.run(debug=True, port=5000)
