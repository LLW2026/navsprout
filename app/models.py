import ipaddress
import re
import unicodedata
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Category(Model):
    name: str = Field(min_length=1, max_length=80)
    sort_order: int = Field(default=0, ge=-1000000, le=1000000)

    @field_validator('name')
    @classmethod
    def normalized(cls, value):
        return unicodedata.normalize('NFC', value)


class LinkFields(Model):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    category: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    icon: str | None = Field(default=None, max_length=16)
    pinned: bool | None = None
    sort_order: int | None = Field(default=None, ge=-1000000, le=1000000)
    organization: Literal['个人', '工作', '其他'] | None = None
    network: Literal['public', 'lan'] | None = None
    environment: Literal['production', 'test', 'none'] | None = None

    @field_validator('url')
    @classmethod
    def valid_url(cls, value):
        if value is None:
            return value
        if any(c.isspace() or ord(c) < 32 or c in '\\<>"' for c in value):
            raise ValueError('网址格式不正确')
        try:
            p = urlsplit(value)
            if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
                raise ValueError()
            if p.port is not None and not 1 <= p.port <= 65535:
                raise ValueError()
            host = p.hostname
            try:
                ipaddress.ip_address(host)
            except ValueError:
                encoded = host.encode('idna').decode('ascii')
                if len(encoded) > 253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', s) for s in encoded.rstrip('.').split('.')):
                    raise ValueError()
        except (ValueError, UnicodeError):
            raise ValueError('请填写有效的 HTTP 或 HTTPS 网址') from None
        return value

    @field_validator('category')
    @classmethod
    def normalize_category(cls, value):
        return unicodedata.normalize('NFC', value) if value else value

    @field_validator('*', mode='before')
    @classmethod
    def no_explicit_null(cls, value):
        if value is None:
            raise ValueError('字段不能为 null；清空说明或图标请传空字符串')
        return value


class Upsert(LinkFields):
    key: str = Field(pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$')
    move_category: bool = False
    update_presentation: bool = False


class Create(LinkFields):
    key: str | None = Field(default=None, pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$')
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=2048)


class ImportLink(LinkFields):
    key: str = Field(pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$')
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=2048)
    category: str = Field(min_length=1, max_length=80)
    created_at: str | None = Field(default=None, max_length=40)
    updated_at: str | None = Field(default=None, max_length=40)


class ImportData(Model):
    version: Literal[1]
    categories: list[Category] = Field(max_length=500)
    links: list[ImportLink] = Field(max_length=10000)
    exported_at: str | None = None


class Login(Model):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=1024)


class DeleteCategory(Model):
    move_to: int | None = None


class Reorder(Model):
    keys: list[str] = Field(min_length=1, max_length=10000)
    complete: bool = False
    category_id: int | None = Field(default=None, gt=0)


class CategoryOrder(Model):
    ids: list[int] = Field(min_length=1, max_length=500)


class MoveLink(Model):
    key: str = Field(min_length=1, max_length=128)
    before_key: str | None = Field(default=None, min_length=1, max_length=128)
    category_id: int | None = Field(default=None, gt=0)
    pinned: bool | None = None


class BatchItem(LinkFields):
    key: str = Field(pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$')


class BatchEdit(Model):
    items: list[BatchItem] = Field(min_length=1, max_length=500)
    operation: Literal['update', 'move', 'pin', 'unpin', 'delete'] = 'update'
    category_id: int | None = Field(default=None, gt=0)
