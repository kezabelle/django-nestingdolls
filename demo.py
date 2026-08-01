import base64
import hashlib
import os
import pprint
import sys
import textwrap
from typing import ClassVar

import django
from django import forms
from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse
from django.template import Context, Template
from django.urls import path
from django.views import View

import nestingdolls
from nestingdolls import ListField

HERE = os.path.abspath(os.path.dirname(__file__))

if not settings.configured:
    settings.configure(
        SECRET_KEY="??????????????????????????????????????????????????????????",
        DEBUG=True,
        INSTALLED_APPS=(
            "django.contrib.staticfiles",
            "nestingdolls",
            "debug_toolbar",
        ),
        ALLOWED_HOSTS=("*",),
        ROOT_URLCONF=__name__,
        MIDDLEWARE=(
            "django.middleware.gzip.GZipMiddleware",
            "django.middleware.http.ConditionalGetMiddleware",
            "debug_toolbar.middleware.DebugToolbarMiddleware",
        ),
        USE_I18N=True,
        USE_TZ=True,
        STATIC_URL="/static/",
        TIME_ZONE="UTC",
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "DIRS": [],
                "APP_DIRS": True,
                "OPTIONS": {},
            },
        ],
        INTERNAL_IPS=[
            "127.0.0.1",
        ],
    )
    django.setup()

favicon = b"\x00\x00\x01\x00\x01\x00\x10\x10\x00\x00\x01\x00 \x00h\x04\x00\x00\x16\x00\x00\x00(\x00\x00\x00\x10\x00\x00\x00 \x00\x00\x00\x01\x00 \x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\xff\x00\xff\xff\x00\x00\xff\xff\x00\x00\xff\xff\x00\x00\xff\xff\x00\x00\xff\xff\x00\x00\xff\xff\x00\x00\xff\xff\x00\x00\xff\xff\x00\x00\xff\xff\x00\x00\xff\xff\x00\x00\xff\xff\x00\x00\xff\xff\x00\x00\xff\xff\x00\x00\xff\xff\x00\x00\xff\xff\x00\x00\xff\xff\x00\x00"
favicon_etag = hashlib.sha1(favicon).hexdigest()
favicon_b64 = base64.b64encode(favicon).decode("utf-8")


class FaviconView(View):
    def get(self, request: WSGIRequest) -> HttpResponse:
        return HttpResponse(
            favicon, content_type="image/x-icon", headers={"Etag": favicon_etag}
        )


class AddressForm(forms.Form):
    street = forms.CharField()
    city = forms.CharField()
    postcode = forms.CharField()


class ContactForm(forms.Form):
    name = forms.CharField()
    email = forms.EmailField()


class ListsForm(forms.Form):
    scores = ListField(forms.IntegerField(min_value=0), min_length=1, max_length=4)
    emails = ListField(forms.EmailField(), required=False, max_length=4)


class MappingsForm(forms.Form):
    billing_address = nestingdolls.MappingField(AddressForm)
    emergency_contact = nestingdolls.MappingField(ContactForm, required=False)


class LineItemForm(forms.Form):
    description = forms.CharField()
    quantity = forms.IntegerField(min_value=1)


class ListOfMappingsForm(forms.Form):
    items = ListField(
        nestingdolls.MappingField(LineItemForm), min_length=1, max_length=5
    )


class MilestoneForm(forms.Form):
    title = forms.CharField()
    reviewers = ListField(forms.EmailField(), required=False, max_length=3)


class ProjectForm(forms.Form):
    name = forms.CharField()
    milestones = ListField(
        nestingdolls.MappingField(MilestoneForm), min_length=1, max_length=4
    )


class DeeplyNestedForm(forms.Form):
    project = nestingdolls.MappingField(ProjectForm)


class CollectionTypesForm(forms.Form):
    coordinates = nestingdolls.TupleField(
        forms.DecimalField(max_digits=5, decimal_places=2), min_length=2, max_length=3
    )
    tags = nestingdolls.SetField(forms.SlugField(), min_length=1, max_length=5)


PAGES = (
    ("lists", "Lists"),
    ("mappings", "Mappings"),
    ("list-of-mappings", "List of mappings"),
    ("deeply-nested", "Deep nesting"),
    ("collection-types", "Tuple and set"),
)

DEMO_TEMPLATE = Template(
    textwrap.dedent("""\
<!DOCTYPE html>
<html lang="en">
    <head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Nesting Doll Forms (Demo)</title>
    <style type="text/css">
    body {
        max-width: 60rem;
        margin: 1rem auto;
        font-family: system-ui, -apple-system, sans-serif;
        font-size: 1rem;
    }
    button[type="submit"], a[href] {
        border: 0;
        background: transparent;
        text-decoration: underline;
        font-size: 1rem;
        padding: 0;
        margin: 0;
        display: inline;
        line-height: normal;
        cursor: pointer;
        color: #0000FF;
    }
    nav a { margin-right: 1rem; }
    form > div,
    form fieldset > div {
        display: flex;
        flex-direction: column;
        margin: 1rem 0;
    }
    form label {
        cursor: pointer;
        font-weight: bold;
        margin-bottom: 0.5rem;
    }
    form input {
        border-radius: 3px;
        border: 1px solid black;
        font-size: 1rem;
        padding: 0.5rem;
    }
    </style>
    </head>
    <body>

    <nav>
    <ul>{% for url_name, label in pages %}<li><a href="{% url url_name %}">{{ label }}</a></li>{% endfor %}</ul>
    </nav>
    <h1>{{ title }}</h1>
    <p>{{ description }}</p>

    <form method="GET" action="" autocomplete="off">
    {{ form }}
    {{ form.media }}
    <button type="submit" name="do-it" value="yep">Submit</button>
    <a href="{{ reset_url }}">Reset</a>
    </form>

    {% if output %}
    <hr>
    <pre>{{ output }}</pre>
    {% endif %}

    </body>
</html>
    """)
)


class DemoView(View):
    form_class: ClassVar[type[forms.Form]]
    title: ClassVar[str]
    description: ClassVar[str]
    initial: ClassVar[dict[str, object]]

    def get_form(self, request: WSGIRequest) -> forms.Form:
        return self.form_class(data=request.GET or None, initial=self.initial)

    def get_output(self, form: forms.Form) -> str:
        if form.is_bound and form.is_valid():
            return pprint.pformat(form.cleaned_data, indent=4, sort_dicts=True)
        return ""

    def get_context_data(
        self, *, form: forms.Form, request: WSGIRequest
    ) -> dict[str, object]:
        return {
            "description": self.description,
            "form": form,
            "output": self.get_output(form),
            "pages": PAGES,
            "reset_url": request.path,
            "title": self.title,
        }

    def get(self, request: WSGIRequest) -> HttpResponse:
        form = self.get_form(request)
        return HttpResponse(
            DEMO_TEMPLATE.render(
                Context(self.get_context_data(form=form, request=request))
            )
        )


class ListsView(DemoView):
    form_class = ListsForm
    title = "Lists"
    description = "Scalar child fields with minimum and maximum lengths."
    initial: ClassVar[dict[str, object]] = {
        "scores": [3, 8],
        "emails": ["Ada@example.com"],
    }


class MappingsView(DemoView):
    form_class = MappingsForm
    title = "Mappings"
    description = "A required address and an optional contact form."
    initial: ClassVar[dict[str, object]] = {
        "billing_address": {
            "street": "1 Python Way",
            "city": "London",
            "postcode": "SW1A 1AA",
        }
    }


class ListOfMappingsView(DemoView):
    form_class = ListOfMappingsForm
    title = "List of mappings"
    description = "Add and remove structured line items."
    initial: ClassVar[dict[str, object]] = {
        "items": [{"description": "Widget", "quantity": 2}]
    }


class DeeplyNestedView(DemoView):
    form_class = DeeplyNestedForm
    title = "Deep nesting"
    description = (
        "A mapping containing a list of mappings, each containing another list."
    )
    initial: ClassVar[dict[str, object]] = {
        "project": {
            "name": "Nesting Dolls",
            "milestones": [{"title": "Demo", "reviewers": ["Grace@example.com"]}],
        }
    }


class CollectionTypesView(DemoView):
    form_class = CollectionTypesForm
    title = "Tuple and set"
    description = "Sequence widgets with tuple and deduplicated set cleaned values."
    initial: ClassVar[dict[str, object]] = {
        "coordinates": (51.51, -0.13),
        "tags": {"django", "forms"},
    }


from debug_toolbar.toolbar import debug_toolbar_urls  # type: ignore[import-not-found]

urlpatterns = [
    path("favicon.ico", FaviconView.as_view(), name="favicon"),
    path("", ListsView.as_view(), name="lists"),
    path("mappings/", MappingsView.as_view(), name="mappings"),
    path("list-of-mappings/", ListOfMappingsView.as_view(), name="list-of-mappings"),
    path("deeply-nested/", DeeplyNestedView.as_view(), name="deeply-nested"),
    path("collection-types/", CollectionTypesView.as_view(), name="collection-types"),
] + debug_toolbar_urls()

if __name__ == "__main__":
    from django.core import management

    argv = sys.argv[:]
    if len(argv) == 1:
        argv.append("runserver")
    management.execute_from_command_line(argv)
else:
    from django.core.wsgi import get_wsgi_application

    application = get_wsgi_application()
