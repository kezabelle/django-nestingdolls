from __future__ import annotations

import base64
import hashlib
import pprint
import sys
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast

import django
from django import forms
from django.conf import settings
from django.contrib.staticfiles.views import serve as serve_static_file
from django.db import models
from django.http import Http404, HttpResponse
from django.template import Context, Template
from django.urls import path
from django.utils.html import format_html
from django.views import View
from django.views.generic.base import RedirectView

import nestingdolls
from nestingdolls import ListField

if TYPE_CHECKING:
    from django.core.handlers.wsgi import WSGIRequest
    from django.utils.safestring import SafeString

HERE = Path(__file__).resolve().parent

if not settings.configured:
    settings.configure(
        SECRET_KEY="??????????????????????????????????????????????????????????",
        DEBUG=True,
        INSTALLED_APPS=(
            "django.contrib.staticfiles",
            "nestingdolls",
        ),
        ALLOWED_HOSTS=("*",),
        ROOT_URLCONF=__name__,
        MIDDLEWARE=(
            "django.middleware.gzip.GZipMiddleware",
            "django.middleware.http.ConditionalGetMiddleware",
        ),
        USE_I18N=True,
        USE_TZ=True,
        STATIC_URL="/static/",
        TIME_ZONE="UTC",
        STATICFILES_DIRS=(HERE,),
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
favicon_etag = hashlib.sha256(favicon).hexdigest()
favicon_b64 = base64.b64encode(favicon).decode("utf-8")


class FaviconView(View):
    def get(self, request: WSGIRequest) -> HttpResponse:  # noqa: ARG002
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


class PlainDjangoForm(forms.Form):
    sku = forms.CharField(label="SKU")
    quantity = forms.IntegerField()


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
    delivery_method = forms.ChoiceField(
        choices=[("standard", "Standard"), ("express", "Express")]
    )
    contact_email = forms.EmailField()
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
    ("plain-django", "Plain Django form"),
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
    <meta name="color-scheme" content="light dark">
    <title>Nesting Doll Forms (Demo)</title>
    {# <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css"> #}
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@anyblades/blades@^3.0.0-0/css/blades.min.css" />
    {% if selected_library == "htmx" %}
    <script src="https://cdn.jsdelivr.net/npm/htmx.org@2.0.10/dist/htmx.min.js" integrity="sha384-H5SrcfygHmAuTDZphMHqBJLc3FhssKjG7w/CeCpFReSfwBWDTKpkzPP8c+cLsK+V" crossorigin="anonymous" defer></script>
    <script src="https://cdn.jsdelivr.net/npm/htmx-ext-preload@2.1.2" integrity="sha384-PRIcY6hH1Y5784C76/Y8SqLyTanY9rnI3B8F3+hKZFNED55hsEqMJyqWhp95lgfk" crossorigin="anonymous" defer></script>
    {% elif selected_library == "unpoly" %}
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/unpoly@3.14/unpoly.min.css">
    <script src="https://cdn.jsdelivr.net/npm/unpoly@3.14/unpoly.min.js" defer></script>
    {% elif selected_library == "taxijs" %}
    <script src="https://cdn.jsdelivr.net/npm/@unseenco/e@2.2.2/dist/e.umd.js" crossorigin defer></script>
    <script src="https://cdn.jsdelivr.net/npm/@unseenco/taxi@1.0.3/dist/taxi.umd.js" crossorigin defer></script>
    <script>
    document.addEventListener("DOMContentLoaded", () => {
      const demoTaxi = new taxi.Core()
      const preloadDemoLinks = () => {
        document.querySelectorAll("a[data-taxi-preload]").forEach((link) => {
          demoTaxi.preload(link.href)
        })
      }
      demoTaxi.on("NAVIGATE_IN", () => {
        document.dispatchEvent(new Event("nestingdolls:sequence-enhance"))
        preloadDemoLinks()
      })
      preloadDemoLinks()
    }, { once: true })
    </script>
    {% elif selected_library == "mujs" %}
    <script src="https://cdn.jsdelivr.net/npm/@digicreon/mujs/dist/mu.min.js" defer></script>
    <script>
    document.addEventListener("DOMContentLoaded", () => {
      mu.init()
    }, { once: true })
    </script>
    {% elif selected_library == "swup" %}
    <script src="https://unpkg.com/swup@4" defer></script>
    <script src="https://unpkg.com/@swup/forms-plugin@3" defer></script>
    <script src="https://unpkg.com/@swup/a11y-plugin@5" defer></script>
    <script src="https://unpkg.com/@swup/preload-plugin@3" defer></script>
    <script>
    document.addEventListener("DOMContentLoaded", () => {
      new Swup({
        plugins: [
          new SwupFormsPlugin(),
          new SwupA11yPlugin(),
          new SwupPreloadPlugin(),
        ],
      })
    }, { once: true })
    </script>
    {% endif %}
    <style>
    .errorlist {
      display: block;
      list-style: none;
      margin-left: 0;
      margin-bottom: var(--pico-typography-spacing-vertical);
      padding: var(--pico-form-element-spacing-vertical)
        var(--pico-form-element-spacing-horizontal);
      background-color: color-mix(
        in srgb,
        var(--pico-form-element-invalid-border-color) 20%,
        transparent
        );
      border: 1px solid var(--pico-form-element-invalid-border-color);
      border-radius: var(--pico-border-radius);
      color: var(--pico-form-element-invalid-active-border-color);
    }
    .errorlist > li {
      list-style: none;
      margin: 0;
    }
    [aria-invalid="true"][aria-describedby$="_error"] +.errorlist[id$="_error"] {
    }
    table th {
      vertical-align: top;
    }
    table td, table th {
        padding-left: 0;
        padding-right: 0;
    }
    ul ul {
      font-size: 100%;
    }
    /*
    html.is-changing .transition-fade {
      transition: opacity 0.15s;
      opacity: 1;
    }
    html.is-animating .transition-fade { opacity: 0; }
    */
    </style>
    </head>
    <body>
    <main{% if selected_library == "swup" %} id="swup" class="container transition-fade"{% else %} class="container"{% endif %}{% if selected_library == "htmx" %} hx-boost="true" hx-ext="preload"{% elif selected_library == "unpoly" %} up-main{% elif selected_library == "taxijs" %} data-taxi{% endif %}>
    {% if selected_library == "taxijs" %}<div data-taxi-view>{% endif %}

    <header>
        <div style="display:flex;justify-content:center;">
            <img src="/logo.png" alt="nestingdolls">
        </div>
        <div>

        <div style="display:flex;justify-content:center;gap: 1rem;">
            <div>
                <details class="dropdown">
                <summary>Examples</summary>
                <ul>{% for url_name, label in pages %}<li><a href="{% url url_name layout=selected_layout jslibrary=selected_library %}"{% if selected_library == "unpoly" %} up-follow{% endif %}{{ preload_attribute }}{% if url_name == current_page %} aria-current="page"{% endif %}>{{ label }}</a></li>{% endfor %}</ul>
                </details>
            </div>
            <div>
                <details class="dropdown">
                <summary >Layouts</summary>
                <ul>{% for layout, layout_label in layouts %}<li><a href="{% url current_page layout=layout jslibrary=selected_library %}"{% if selected_library == "unpoly" %} up-follow{% endif %}{% if layout == selected_layout %} aria-current="page"{% endif %}>{{ layout_label }}</a></li>{% endfor %}</ul>
                </details>
            </div>
            <div>
                <details class="dropdown">
                <summary>JavaScript</summary>
                <ul>{% for library, library_label in libraries %}<li><a href="{% url current_page layout=selected_layout jslibrary=library %}" hx-boost="false" up-follow="false" data-taxi-ignore mu-disabled data-no-swup {% if library == selected_library %} aria-current="page"{% endif %}>{{ library_label }}</a></li>{% endfor %}</ul>
                </details>
            </div>
        </div>

        <section style="text-align:center;padding: 1rem 0;margin: 0;">
        <h1 style="margin:0; font-size: 1rem;">{{ title }}</h1>
        <h2 style="font-size: 0.75rem;font-weight:normal;margin:0;">{{ description }}</h2>
        </section>

        </div>
    </header>
    {% if output %}
    <dialog open closedby="closerequest">
    <article>
    {% spaceless %}
    <pre style="background:var(--pico-code-background-color) !important;">
    <code data-caption="form.cleaned_data">{{ output }}</code>
    </pre>
    {% endspaceless %}
    <footer>
      <form method="dialog">
        <button class="secondary" value="close">Close</button>
      </form>
    </footer>
    </dialog>
    {% endif %}

    <section>
    <form method="GET" action="{{ reset_url }}" autocomplete="off"{% if selected_library == "unpoly" %} up-submit{% elif selected_library == "swup" %} data-swup-form{% endif %}>
    {{ form_html }}
    {{ form.media }}
    <div class="grid">
    <button type="submit" name="do-it" value="yep">Submit</button>
    <a href="{{ reset_url }}" role="button" class="outline secondary"{% if selected_library == "unpoly" %} up-follow{% endif %}{{ preload_attribute }}>Reset</a>
    </div>
    </form>
    {% if selected_library == "taxijs" %}</div>{% endif %}
    </main>
    </section>
    </body>
</html>
    """)
)


class DemoView(View):
    form_class: ClassVar[type[forms.Form]]
    title: ClassVar[str]
    description: ClassVar[str]
    initial: ClassVar[dict[str, object]]
    form: forms.Form

    class Layout(models.TextChoices):
        DIV = "as_div", "as <div>"
        P = "as_p", "as <p>"
        TABLE = "as_table", "as <table>"
        UL = "as_ul", "as <ul>"

    class Library(models.TextChoices):
        NONE = "none", "None"
        HTMX = "htmx", "htmx"
        UNPOLY = "unpoly", "Unpoly"
        TAXI = "taxijs", "Taxi.js"
        MU = "mujs", "µJS"
        SWUP = "swup", "swup"

        @property
        def preload_attribute(self) -> str | None:
            if self is self.HTMX:
                return "preload"
            if self is self.UNPOLY:
                return "up-preload"
            if self is self.TAXI:
                return "data-taxi-preload"
            if self is self.SWUP:
                return "data-swup-preload"
            return None

    def get_selected_config(self) -> tuple[Layout, Library]:
        selected_layout = cast("str", self.kwargs["layout"])
        selected_library = cast("str", self.kwargs["jslibrary"])
        try:
            layout = self.Layout(selected_layout)
            library = self.Library(selected_library)
        except ValueError:
            raise Http404("Unknown demo configuration") from None
        return layout, library

    def get_form(self, request: WSGIRequest) -> forms.Form:
        return self.form_class(data=request.GET or None, initial=self.initial)

    def get_form_html(self, form: forms.Form, selected_layout: str) -> SafeString:
        rendered: SafeString = getattr(form, selected_layout)()
        return rendered

    def get_output(self, form: forms.Form) -> str:
        if form.is_bound and form.is_valid():
            return pprint.pformat(
                form.cleaned_data,
                indent=4,
                width=40,
                sort_dicts=True,
                underscore_numbers=True,
            )
        return ""

    def get_context_data(self, *, request: WSGIRequest) -> dict[str, object]:
        current_page: str = ""
        if request.resolver_match:
            current_page = request.resolver_match.url_name or ""
        selected_layout, selected_library = self.get_selected_config()
        preload_attribute = selected_library.preload_attribute
        return {
            "current_page": current_page,
            "description": self.description,
            "form": self.form,
            "form_html": self.get_form_html(self.form, selected_layout),
            "layouts": self.Layout.choices,
            "libraries": self.Library.choices,
            "preload_attribute": (
                format_html(" {}", preload_attribute) if preload_attribute else ""
            ),
            "output": self.get_output(self.form),
            "pages": PAGES,
            "reset_url": request.path,
            "selected_layout": selected_layout,
            "selected_library": selected_library,
            "title": self.title,
        }

    def get(
        self,
        request: WSGIRequest,
        *_args: object,
        **_kwargs: object,
    ) -> HttpResponse:
        self.form = self.get_form(request)
        return HttpResponse(
            DEMO_TEMPLATE.render(Context(self.get_context_data(request=request)))
        )


class PlainDjangoView(DemoView):
    form_class = PlainDjangoForm
    title = "Plain Django form"
    description = "A regular Django IntegerField without a nestingdolls field."
    initial: ClassVar[dict[str, object]] = {"quantity": 1}


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
    description = "Choose delivery details and add structured line items."
    initial: ClassVar[dict[str, object]] = {
        "delivery_method": "standard",
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


urlpatterns = [
    path("favicon.ico", FaviconView.as_view(), name="favicon"),
    path(
        "logo.png",
        serve_static_file,
        {"path": "nestingdolls.png"},
        name="logo",
    ),
    path(
        "",
        RedirectView.as_view(
            url=(
                f"/lists/layout:{DemoView.Layout.DIV.value}/"
                f"js:{DemoView.Library.HTMX.value}/"
            ),
        ),
    ),
    path(
        "flat/layout:<str:layout>/js:<str:jslibrary>/",
        PlainDjangoView.as_view(),
        name="plain-django",
    ),
    path(
        "lists/layout:<str:layout>/js:<str:jslibrary>/",
        ListsView.as_view(),
        name="lists",
    ),
    path(
        "mappings/layout:<str:layout>/js:<str:jslibrary>/",
        MappingsView.as_view(),
        name="mappings",
    ),
    path(
        "list-of-mappings/layout:<str:layout>/js:<str:jslibrary>/",
        ListOfMappingsView.as_view(),
        name="list-of-mappings",
    ),
    path(
        "deeply-nested/layout:<str:layout>/js:<str:jslibrary>/",
        DeeplyNestedView.as_view(),
        name="deeply-nested",
    ),
    path(
        "collection-types/layout:<str:layout>/js:<str:jslibrary>/",
        CollectionTypesView.as_view(),
        name="collection-types",
    ),
]

if __name__ == "__main__":
    from django.core import management

    argv = sys.argv[:]
    if len(argv) == 1:
        argv.append("runserver")
    management.execute_from_command_line(argv)
else:
    from django.core.wsgi import get_wsgi_application

    application = get_wsgi_application()
