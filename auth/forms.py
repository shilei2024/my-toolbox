"""WTForms for auth flows."""
from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField
from wtforms.validators import DataRequired, Email, Length


class LoginForm(FlaskForm):
    email = StringField("邮箱", validators=[DataRequired("请输入邮箱"), Email("邮箱格式不正确")])
    password = PasswordField("密码", validators=[DataRequired("请输入密码"), Length(min=6, max=128)])
    remember = BooleanField("记住我", default=True)


class RegistrationEmailForm(FlaskForm):
    email = StringField("邮箱", validators=[DataRequired("请输入邮箱"),
        Email("邮箱格式不正确"), Length(max=255)])
