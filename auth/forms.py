"""WTForms for auth flows."""
from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Regexp


class LoginForm(FlaskForm):
    email = StringField("邮箱", validators=[DataRequired("请输入邮箱"), Email("邮箱格式不正确")])
    password = PasswordField("密码", validators=[DataRequired("请输入密码"), Length(min=6, max=128)])
    remember = BooleanField("记住我", default=True)


class RegisterForm(FlaskForm):
    email = StringField(
        "邮箱",
        validators=[
            DataRequired("请输入邮箱"),
            Email("邮箱格式不正确"),
            Length(max=255),
        ],
    )
    password = PasswordField(
        "密码",
        validators=[
            DataRequired("请输入密码"),
            Length(min=8, max=128, message="密码长度需在 8-128 位之间"),
            Regexp(
                r"^(?=.*[A-Za-z])(?=.*\d).+$",
                message="密码必须同时包含字母和数字",
            ),
        ],
    )
    confirm = PasswordField(
        "确认密码",
        validators=[DataRequired("请再次输入密码"), EqualTo("password", message="两次输入的密码不一致")],
    )
