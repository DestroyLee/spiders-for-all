import logging
import typing as t
from http.cookies import SimpleCookie
from itertools import chain

import requests
from requests.cookies import RequestsCookieJar, cookiejar_from_dict
from requests.structures import CaseInsensitiveDict
from rich import console

from spiders_for_all.conf import settings
from spiders_for_all.utils import decorator, helper, logger

LoggerType: t.TypeAlias = console.Console | logging.Logger
Headers: t.TypeAlias = CaseInsensitiveDict


def dict_to_headers(headers: dict[str, t.Any]) -> CaseInsensitiveDict:
    return CaseInsensitiveDict(headers)


def merge_dict(*dicts: t.Unpack[t.Tuple[dict[str, t.Any], ...]]) -> dict[str, t.Any]:
    return dict(chain.from_iterable(d.items() for d in dicts))


class RetrySettings(t.TypedDict):
    max_retries: t.NotRequired[int]
    retry_interval: t.NotRequired[int]
    retry_step: t.NotRequired[int]


class RequestKwargs(t.TypedDict):
    params: t.NotRequired[t.Any]
    data: t.NotRequired[t.Any]
    json: t.NotRequired[t.Any]
    files: t.NotRequired[dict[str, t.Any]]
    auth: t.NotRequired[t.Any]
    timeout: t.NotRequired[t.Any]
    allow_redirects: t.NotRequired[t.Any]
    verify: t.NotRequired[t.Any]
    stream: t.NotRequired[t.Any]
    cert: t.NotRequired[t.Any]
    headers: t.NotRequired[dict]
    cookies: t.NotRequired[dict]
    proxies: t.NotRequired[dict]


class HttpClient(logger.LoggerMixin):
    def __init__(
        self,
        logger: LoggerType = logger.default_logger,
        proxies: dict[str, str] | None = None,
        headers: dict[str, t.Any] | Headers | None = None,
        cookies: dict[str, t.Any] | str | RequestsCookieJar | None = None,
        **retry_settings: t.Unpack[RetrySettings],
    ) -> None:
        super().__init__(logger=logger)
        self.session = requests.Session()
        self.retry_settings = retry_settings

        self.proxies = proxies or settings.HTTP_PROXIES

        self._headers = headers
        self._cookies = cookies

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        self.session.close()

    @property
    def headers(self) -> Headers:
        # Generate random user agent headers every time
        headers_ua = helper.user_agent_headers()

        if self._headers is None:
            self._headers = headers_ua
        else:
            self._headers.update(headers_ua)

        self._headers = dict_to_headers(self._headers)  # type: ignore

        return self._headers

    @property
    def cookies(self) -> RequestsCookieJar:
        if self._cookies is None:
            self._cookies = cookiejar_from_dict({})
            return self._cookies

        if isinstance(self._cookies, RequestsCookieJar):
            return self._cookies
        match self._cookies:
            case str():
                _cookie = SimpleCookie()
                _cookie.load(self._cookies)
                self._cookies = cookiejar_from_dict(
                    {key: morsel.value for key, morsel in _cookie.items()}
                )
            case dict():
                self._cookies = cookiejar_from_dict(self._cookies)
            case _:
                raise TypeError(
                    "Cookies must be a dict,  a string, "
                    f"or a RequestsCookieJar object, but got {type(self._cookies)}."
                )

        return self._cookies

    def new(self):
        """Create a new instance of HttpClient."""

        return HttpClient(
            logger=self.logger,
            proxies=self.proxies,
            headers=self._headers,
            cookies=self._cookies,
            **self.retry_settings,
        )

    def request(
        self, method: str, url: str, **kwargs: t.Unpack[RequestKwargs]
    ) -> requests.Response:
        # TODO: Add hooks to check response with code 200

        # merge cookies, and proxies
        kwargs["cookies"] = merge_dict(dict(self.cookies), kwargs.get("cookies", {}))
        if self.proxies is not None:
            kwargs["proxies"] = merge_dict(self.proxies, kwargs.get("proxies", {}))

        headers_merged = False

        @decorator.retry(
            max_retries=self.retry_settings.get(
                "max_retries", settings.REQUEST_MAX_RETRIES
            ),
            interval=self.retry_settings.get(
                "retry_interval", settings.REQUEST_RETRY_INTERVAL
            ),
            step=self.retry_settings.get("retry_step", settings.REQUEST_RETRY_STEP),
            logger=self.logger,
        )
        def _request():
            nonlocal headers_merged
            if not headers_merged:
                kwargs["headers"] = merge_dict(
                    dict(self.headers), kwargs.get("headers", {})
                )
                headers_merged = True
            else:
                if "headers" in kwargs:
                    # Some time the user-agent may be too old, so we should change it every time
                    kwargs["headers"].update(**helper.user_agent_headers())

            self.debug(f"==> [{method.upper()}] {url} with kwargs: {kwargs}")
            resp = self.session.request(
                method=method,
                url=url,
                **kwargs,
            )
            resp.raise_for_status()
            self.debug(
                f"<== [{resp}] <[{method.upper()}] {resp.request.url}> headers: {self.session.headers} cookies: {self.session.cookies}"
            )
            return resp

        return _request()  # type: ignore

    def get(self, url: str, **kwargs: t.Unpack[RequestKwargs]) -> requests.Response:
        return self.request("get", url, **kwargs)

    def options(self, url: str, **kwargs: t.Unpack[RequestKwargs]) -> requests.Response:
        return self.request("options", url, **kwargs)

    def head(self, url: str, **kwargs: t.Unpack[RequestKwargs]) -> requests.Response:
        kwargs.setdefault("allow_redirects", False)
        return self.request("head", url, **kwargs)

    def post(self, url: str, **kwargs: t.Unpack[RequestKwargs]) -> requests.Response:
        return self.request("post", url, **kwargs)

    def put(self, url: str, **kwargs: t.Unpack[RequestKwargs]) -> requests.Response:
        return self.request("put", url, **kwargs)

    def patch(self, url: str, **kwargs: t.Unpack[RequestKwargs]) -> requests.Response:
        return self.request("patch", url, **kwargs)

    def delete(self, url: str, **kwargs: t.Unpack[RequestKwargs]) -> requests.Response:
        return self.request("delete", url, **kwargs)
