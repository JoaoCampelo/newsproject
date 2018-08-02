# -*- coding: utf-8 -*-

from newsapi import NewsApiClient
import urllib.parse
from bs4 import BeautifulSoup
import xlsxwriter
import requests
import xlrd
import json
from difflib import SequenceMatcher
from flask import Flask, render_template, flash, redirect, url_for, session, request, logging
from flask_mysqldb import MySQL
from wtforms import Form, StringField, TextAreaField, PasswordField, SelectField, validators
from passlib.hash import sha256_crypt
from functools import wraps
from datetime import date
from bs4 import BeautifulSoup
import re
import requests


app = Flask(__name__)

#Configurar Base de Dados
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWPRD'] = ''
app.config['MYSQL_DB'] = 'newsproject_db'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'
#Inicializar Base de Dados
mysql = MySQL(app)

def is_logged_in(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if 'logged_in' in session:
            return f(*args, **kwargs)
        else:
            flash('Acesso não autorizado! Faça login para continuar.','danger')
            return redirect(url_for('login'))
    return wrap

@app.route('/')
def index():
    cur = mysql.connection.cursor()
    result = cur.execute("SELECT * FROM noticias ORDER BY idnoticias DESC LIMIT 8")
    noticias = cur.fetchall()

    if result > 0:
        return render_template('home.html', noticias=noticias)
    else:
        msg = "Não foram encontradas avaliações!"
        return render_template('home.html', msg=msg)

    cur.close()

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/noticia/<string:id>/')
def noticia(id):
    cur = mysql.connection.cursor()
    result = cur.execute("SELECT * FROM noticias WHERE idnoticias=%s", [id])
    noticia = cur.fetchone()

    verdade = tratar_dados(noticia)

    return render_template('noticia.html', noticia=noticia, verdade=verdade)

@app.route('/noticias', methods=['GET'])
def noticias():
    cur = mysql.connection.cursor()
    offsets = 8*(int(request.args['page'])-1)
    result = cur.execute("SELECT * FROM noticias LIMIT 8 OFFSET %s", [offsets])
    noticias = cur.fetchall()

    pages = cur.execute("SELECT COUNT(*) AS testes FROM noticias")
    pages = cur.fetchone()
    pages = (int(pages['testes']) / 8) + 1

    pageAnt = 0;
    pageProx = int(request.args['page']) + 1

    if (int(request.args['page']) > 1) :
        pageAnt = int(request.args['page']) - 1

    if result > 0:
        return render_template('noticias.html', noticias=noticias, pageAnt="/noticias?page=" + str(pageAnt), pageProx="/noticias?page=" + str(pageProx), pages=int(pages), bloackAnt=int(pageAnt), blockProx=int(pageProx))
    else:
        flash('Não foram encontrados noticias!.','danger')
        return render_template('noticias.html', pageAnt="/noticias?page=" + str(pageAnt), pageProx="/noticias?page=" + str(pageProx), pages=int(pages))

    cur.close()

@app.route('/avaliarNoticias', methods=['GET', 'POST'])
@is_logged_in
def avaliarNoticias():
    form = request.form
    if request.method == 'POST':
        urlNoticia = request.form['url']
        print("Url a avaliar: " + urlNoticia)
        cur = mysql.connection.cursor()
        result = cur.execute("SELECT * FROM noticias")
        noticia1 = cur.fetchall()
        for item in noticia1:
            racio = comparar(urlNoticia, item['urlnoticia'])
            if(racio > 0.65):
                verdade = tratar_dados(item)
                return render_template('noticia.html', noticia=item, verdade=verdade)

        urls = re.findall('https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+', urlNoticia)
        if not(urls):
            flash('Insira um URL válido','danger')
            return render_template('avaliarNoticias.html')
        urlfinal = urlNoticia.replace(urls[0], '')

        titulo_noticia = get_titulo_noticia(urlNoticia)
        print("Titulo: " + titulo_noticia)

        palavras_chave = chamar_API_analise_texto(titulo_noticia)
        print(palavras_chave)

        racio_igualdade = 0
        total_dados = []
        total_resultados = 0
        url_final = ""
        for palavra in palavras_chave:
            dados_noticia = chamar_API_noticias(palavra)
            total_resultados = total_resultados + dados_noticia.get('totalResults')
            total_dados.append(dados_noticia)

            for url_dados in dados_noticia.get('articles'):
                racio = comparar(urlNoticia, url_dados.get("url"))
                #print(racio)
                if(racio > 0.5 and racio > racio_igualdade):
                    url_final = url_dados.get("url")
                    racio_igualdade = racio
                    noticia = url_dados
        print("URL Final: " + url_final)

        if(url_final != ""):
            texto_noticia = apanhar_texto_noticia(noticia.get('url'))
            #print("Texto da noticia: " + texto_noticia)
        else:
            flash('Esta noticia não foi encontrada pela nossa API. É probavel que seja falsa.','danger')
            return render_template('avaliarNoticias.html')

        plagio_noticia = 0
        count_comparadas = 0
        for dados in total_dados:
            for comparar_texto in dados.get('articles'):
                texto_comparar = apanhar_texto_noticia(comparar_texto.get('url'))
                percentagem_igualdade = comparar(texto_comparar, texto_noticia)
                if(percentagem_igualdade > 0.3):
                    plagio_noticia = plagio_noticia + percentagem_igualdade
                    count_comparadas = count_comparadas + 1
        media_plagio = plagio_noticia / count_comparadas
        #print(media_plagio)

        guardar_noticia(total_resultados, noticia, texto_noticia, media_plagio, count_comparadas)

        cur = mysql.connection.cursor()
        result = cur.execute("SELECT * FROM noticias WHERE idnoticias=(SELECT MAX(idnoticias) FROM noticias)")
        noticiaa = cur.fetchone()

        verdade = tratar_dados(noticiaa)
        return render_template('noticia.html', noticia=noticiaa, verdade=verdade)

    return render_template('avaliarNoticias.html')




def get_nome_site(url):
    webpage = requests.get(url, params=None)
    soup = BeautifulSoup(webpage.text, 'html.parser')

    nome_site = soup.find('title').get_text()

    return nome_site

def get_titulo_noticia(url):
    webpage = requests.get(url, params=None)
    soup = BeautifulSoup(webpage.text, 'html.parser')

    titulo_noticia = ""
    for link in soup.find_all('h1'):
        if(len(titulo_noticia) < len(link.get_text())):
            titulo_noticia = link.get_text()

    return titulo_noticia

def chamar_API_analise_texto(titulo):
    subscription_key = '56a5b1f568e442f2ab31d724795cc844'
    assert subscription_key
    text_analytics_base_url = "https://westcentralus.api.cognitive.microsoft.com/text/analytics/v2.0/keyPhrases"
    headers = {"Ocp-Apim-Subscription-Key": subscription_key}
    json = {'documents': [{'id': '1', 'text': titulo}]}
    result = requests.post(text_analytics_base_url, headers=headers, json=json)
    key_phrases = result.json()

    palavras_chave = []

    for link in key_phrases["documents"]:
        for keyPhrase in link["keyPhrases"]:
            palavras_chave.append(keyPhrase)

    return palavras_chave


def chamar_API_noticias(titulo):
    titulo = urllib.parse.quote(titulo)
    webpage = requests.get("https://newsapi.org/v2/everything?q="+ titulo +"&apiKey=d8f8518262fb4649985eab4463aaa164", params=None)
    json_data = json.loads(webpage.text)

    return json_data



def comparar(dado1, dado2):
    similarity_ratio = SequenceMatcher(None, dado1, dado2).ratio()

    return similarity_ratio

def comparar_datas(data_noticia_original, data_noticia_comparar):
    d1 = data_noticia_original.toordinal()
    d2 = data_noticia_comparar.toordinal()
    quantidade_dias = abs(d2 - d1)
    print(quantidade_dias)
    return quantidade_dias

def apanhar_texto_noticia(url):
    webpage = requests.get(url, params=None)
    soup = BeautifulSoup(webpage.text, 'html.parser')

    texto = ''
    for link in soup.find_all('p'):
        texto = texto + link.get_text()

    return texto

def guardar_noticia(total_resultados, noticia, texto_noticia, media_plagio, noticias_aceites):
    #Criar Query
    cur = mysql.connection.cursor()
    cur.execute("INSERT INTO noticias(fonte, autor, titulo, descricao, noticia, urlnoticia, urlimagem, datapublicacao, totalresultados, madiaplagio, noticiasaceites) VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", (noticia.get('source')["name"], noticia.get('author'), noticia.get('title'), noticia.get('description'), texto_noticia, noticia.get('url'), noticia.get('urlToImage'), noticia.get('publishedAt'), total_resultados, media_plagio, noticias_aceites))
    #Inserir na base de Dados
    mysql.connection.commit()
    #Fechar ligacao a base de dados
    cur.close()

def tratar_dados(noticia):
    if(noticia['fonte']):
        efonte = 1
    else:
        efonte = 0

    if(noticia['autor']):
        eautor = 1
    else:
        eautor = 0

    if(noticia['urlimagem']):
        eimagem = 1
    else:
        eimagem = 0

    noticias_aceites = float('%0.2f' % ((noticia['noticiasaceites'] * 1)/noticia['totalresultados']))


    diferenca_dias = comparar_datas(noticia['datapublicacao'], date.today())
    if(diferenca_dias<31):
        edata = 1
    else:
        edata = 0

    verdade = float('%0.2f' % (((edata*0.3) + (noticias_aceites*0.15) + (noticia['madiaplagio']*0.133) + (efonte*0.183) + (eautor*0.183) + (eimagem*0.05))*100))
    return verdade

class RegisterForm(Form):
    name = StringField('Username', [
        validators.Length(min = 1, max = 200, message = 'Introduza entre 1 e 75 caracteres.'),
        validators.InputRequired(message = 'Campo de preenchimento obrigatório!')
        ])
    email = StringField('Email', [
        validators.Length(min = 1, max = 200, message = 'Introduza entre 1 e 75 caracteres.'),
        validators.InputRequired(message = 'Campo de preenchimento obrigatório!')
        ])

    password = PasswordField('Password', [
        validators.DataRequired(),
        validators.InputRequired(message = 'Campo de preenchimento obrigatório!'),
        validators.EqualTo('confirm_password', message='As passwords não são iguais.')
    ])
    confirm_password = PasswordField('Confirm Password')

@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm(request.form)
    if request.method == 'POST' and form.validate():
        name = form.name.data
        email = form.email.data
        password = sha256_crypt.encrypt(str(form.password.data))

        #Criar Query
        cur = mysql.connection.cursor()
        cur.execute("INSERT INTO users(nome, email, password) VALUES(%s, %s, %s)", (name, email, password))
        #Inserir na base de Dados
        mysql.connection.commit()
        #Fechar ligacao a base de dados
        cur.close()

        flash('Registado com sucesso! Pode fazer login.', 'success')

        return redirect(url_for('login'))

    return render_template('register.html', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Get Form Fields
        email = request.form['email']
        password_candidate = request.form['password']

        # Create cursor
        cur = mysql.connection.cursor()

        # Get user by username
        result = cur.execute("SELECT * FROM users WHERE email = %s", [email])

        if result > 0:
            # Get stored hash
            data = cur.fetchone()
            password = data['password']

            # Compare Passwords
            if sha256_crypt.verify(password_candidate, password):
                # Passed
                session['logged_in'] = True
                session['email'] = email
                session['username'] = data['nome']
                session['privilegios'] = data['privilegios']

                flash('Login efectuado com sucesso.', 'success')
                if(session['privilegios'] == 1):
                    return redirect(url_for('dashboard'))
                else:
                    return redirect(url_for('avaliarNoticias'))
            else:
                error = 'Password inválida!'
                return render_template('login.html', error=error)
            # Close connection
            cur.close()
        else:
            error = 'Utilizador não existe!'
            return render_template('login.html', error=error)

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logout efectuado com sucesso.','success')
    return redirect(url_for('index'))

@app.route('/dashboard')
@is_logged_in
def dashboard():

    return render_template('dashboard.html')



class UserForm(Form):
    id = StringField ('ID', [
        validators.Length(min = 1, max = 200, message = 'Introduza entre 1 e 75 caracteres.'),
        validators.InputRequired(message = 'Campo de preenchimento obrigatório!')
        ])
    username = StringField ('Username', [
        validators.Length(min = 1, message = 'Introduza entre 1 e 75 caracteres.'),
        validators.InputRequired(message = 'Campo de preenchimento obrigatório!')
        ])
    email = StringField ('Username', [
        validators.Length(min = 1, message = 'Introduza entre 1 e 75 caracteres.'),
        validators.InputRequired(message = 'Campo de preenchimento obrigatório!')
        ])
    privilegios = SelectField('Privilégios', choices = [('0', 'Utilizador Normal'),
      ('1', 'Administrador')])

@app.route('/utilizadores')
@is_logged_in
def utilizadores():
    cur = mysql.connection.cursor()
    result = cur.execute("SELECT * FROM users")
    users = cur.fetchall()

    if result > 0:
        return render_template('utilizadores.html', users=users)
    else:
        flash('Não foram utilizadores!','danger')
        return render_template('utilizadores.html')

    cur.close()

@app.route('/eliminar_utilizador/<string:id>', methods=['GET', 'POST'])
@is_logged_in
def eliminar_utilizador(id):
    cur = mysql.connection.cursor()
    result = cur.execute("DELETE FROM users WHERE id=%s", [id])
    mysql.connection.commit()
    cur.close()

    flash('Utilizador eliminado com sucesso.','success')
    return redirect(url_for('utilizadores'))

if __name__ == '__main__':
    app.secret_key='secret123'
    app.run(debug = True)
