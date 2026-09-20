import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


# =========================================================
# CONFIG
# =========================================================

ZIP = "06712"
GALLONS = 100
OUT = Path("data/prices.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1"
    )
}


# =========================================================
# BASIC HELPERS
# =========================================================

def get_html(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30
    )
    response.raise_for_status()
    return response.text


def clean_text(value):
    return re.sub(
        r"\s+",
        " ",
        value
    ).strip()


def soup_text(url):
    html = get_html(url)

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    return clean_text(
        soup.get_text(
            " ",
            strip=True
        )
    )


def extract_price(patterns, text):
    text = clean_text(text)

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I
        )

        if match:

            try:
                return float(
                    match.group(1)
                )
            except Exception:
                continue

    return None


# =========================================================
# PRICE EXTRACTION
# =========================================================

def extract_100_149_price(text):

    patterns = [
        r"100\s*[-–—]\s*149\s*gallons?.{0,300}?\$\s*(\d+\.\d{2,3})",
        r"\$\s*(\d+\.\d{2,3}).{0,300}?100\s*[-–—]\s*149\s*gallons?",
        r"100\s*[-–—]\s*149\s*gal(?:lon)?s?.{0,300}?\$\s*(\d+\.\d{2,3})",
        r"100\s+(?:to|through)\s+149\s+gallons?.{0,300}?\$\s*(\d+\.\d{2,3})",
    ]

    return extract_price(
        patterns,
        text
    )


def extract_100_299_price(text):

    patterns = [
        r"100\s*[-–—]\s*299\s*gallons?.{0,300}?\$\s*(\d+\.\d{2,3})",
        r"\$\s*(\d+\.\d{2,3}).{0,300}?100\s*[-–—]\s*299\s*gallons?",
        r"100\s*[-–—]\s*299\s*gal(?:lon)?s?.{0,300}?\$\s*(\d+\.\d{2,3})",
        r"100\s*[-–—]\s*299.{0,300}?\$\s*(\d+\.\d{2,3})",
    ]

    return extract_price(
        patterns,
        text
    )


def extract_100_plus_price(text):

    patterns = [
        r"100\s*\+\s*gallons?.{0,300}?\$\s*(\d+\.\d{2,3})",
        r"\$\s*(\d+\.\d{2,3}).{0,300}?100\s*\+\s*gallons?",
        r"100\s*\+\s*gal(?:lon)?s?.{0,300}?\$\s*(\d+\.\d{2,3})",
        r"100\s+gallons?\s+(?:and|or)\s+(?:more|over).{0,300}?\$\s*(\d+\.\d{2,3})",
    ]

    return extract_price(
        patterns,
        text
    )


# =========================================================
# FIRST FUEL OIL
# =========================================================

def first_fuel():

    text = soup_text(
        "https://www.firstfueloil.com/"
    )

    price = extract_100_299_price(text)

    if price is not None:

        return (
            price,
            "Published 100-299 gallon price"
        )

    price = extract_100_149_price(text)

    if price is not None:

        return (
            price,
            "Published 100-149 gallon price"
        )

    raise RuntimeError(
        "Could not find First Fuel 100-gallon price"
    )


# =========================================================
# PHILLIPS OIL
# =========================================================

def phillips():

    html = get_html(
        "https://phillipsoilllc.com/"
    )

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    # Phillips publishes a pricing table.
    for table in soup.find_all("table"):

        rows = table.find_all("tr")

        for row in rows:

            cells = [
                clean_text(
                    cell.get_text(
                        " ",
                        strip=True
                    )
                )
                for cell in row.find_all(
                    ["td", "th"]
                )
            ]

            if not cells:
                continue

            if cells[0].strip() == "100":

                for cell in cells[1:]:

                    match = re.search(
                        r"\$\s*(\d+\.\d{2,3})",
                        cell
                    )

                    if match:

                        return (
                            float(
                                match.group(1)
                            ),
                            "Published 100-gallon price"
                        )

    text = clean_text(
        soup.get_text(
            " ",
            strip=True
        )
    )

    price = extract_100_299_price(text)

    if price is not None:

        return (
            price,
            "Published 100-299 gallon price"
        )

    raise RuntimeError(
        "Could not find Phillips 100-gallon price"
    )


# =========================================================
# CURTISS OIL
# =========================================================

def curtiss():

    url = "https://curtissoil.com/get-price/"

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        )

        page = browser.new_page(
            viewport={
                "width": 1440,
                "height": 1200
            }
        )

        network_responses = []

        def handle_response(response):

            try:

                response_url = response.url.lower()

                if any(
                    term in response_url
                    for term in [
                        "price",
                        "quote",
                        "fuel",
                        "product",
                        "order",
                        "api",
                        "ajax"
                    ]
                ):

                    network_responses.append(
                        response
                    )

            except Exception:
                pass

        page.on(
            "response",
            handle_response
        )

        try:

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000
            )

            page.wait_for_timeout(
                5000
            )

            # -------------------------------------------------
            # SEARCH ALL FRAMES FOR ZIP
            # -------------------------------------------------

            zip_box = None
            zip_frame = None

            for frame in page.frames:

                try:

                    candidates = frame.locator(
                        "input"
                    )

                    for i in range(
                        candidates.count()
                    ):

                        candidate = candidates.nth(i)

                        metadata = candidate.evaluate(
                            """
                            el => ({
                                name: el.name || "",
                                id: el.id || "",
                                placeholder: el.placeholder || "",
                                aria: el.getAttribute("aria-label") || "",
                                type: el.type || ""
                            })
                            """
                        )

                        combined = " ".join(
                            str(v)
                            for v in metadata.values()
                        ).lower()

                        if (
                            "zip" in combined
                            or "postal" in combined
                        ):

                            zip_box = candidate
                            zip_frame = frame
                            break

                except Exception:
                    continue

                if zip_box is not None:
                    break

            if zip_box is None:

                raise RuntimeError(
                    "Curtiss ZIP input not found"
                )

            zip_box.fill(
                ZIP
            )

            # -------------------------------------------------
            # CHECK PRICE
            # -------------------------------------------------

            check_button = None

            for selector in [
                'button:has-text("Check Price")',
                'button:has-text("Check price")',
                'button:has-text("Check")',
                'button:has-text("Price")',
                'input[type="submit"]',
            ]:

                try:

                    locator = zip_frame.locator(
                        selector
                    )

                    if locator.count() > 0:

                        check_button = locator.first
                        break

                except Exception:
                    continue

            if check_button is None:

                raise RuntimeError(
                    "Curtiss Check Price button not found"
                )

            check_button.click()

            page.wait_for_timeout(
                10000
            )

            # -------------------------------------------------
            # SEARCH ALL FRAMES
            # -------------------------------------------------

            diagnostic = []

            for frame in page.frames:

                try:

                    body = clean_text(
                        frame.locator(
                            "body"
                        ).inner_text(
                            timeout=5000
                        )
                    )

                    if body:
                        diagnostic.append(body)

                    price = extract_100_plus_price(
                        body
                    )

                    if price is not None:

                        browser.close()

                        return (
                            price,
                            "ZIP-specific 100+ gallon price"
                        )

                except Exception:
                    continue

            # -------------------------------------------------
            # NETWORK FALLBACK
            # -------------------------------------------------

            for response in network_responses:

                try:

                    content_type = (
                        response.headers.get(
                            "content-type",
                            ""
                        ).lower()
                    )

                    if (
                        "json" in content_type
                        or "text" in content_type
                        or "javascript" in content_type
                        or "html" in content_type
                    ):

                        response_text = response.text()

                        price = extract_100_plus_price(
                            response_text
                        )

                        if price is not None:

                            browser.close()

                            return (
                                price,
                                "ZIP-specific 100+ gallon price"
                            )

                except Exception:
                    continue

            print(
                "\n----- CURTISS DIAGNOSTIC -----\n"
            )

            print(
                "\n\n".join(diagnostic)[:15000]
            )

            browser.close()

            return (
                None,
                "ZIP accepted, but Curtiss price was not found."
            )

        except Exception as error:

            try:
                browser.close()
            except Exception:
                pass

            return (
                None,
                "Curtiss quote failed: "
                + type(error).__name__
                + ": "
                + str(error)[:250]
            )


# =========================================================
# GENERIC DROPLET / EMBEDDED QUOTE PAGE
# =========================================================

def quote_page_100_plus(
    url,
    supplier_name
):

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        )

        page = browser.new_page(
            viewport={
                "width": 1440,
                "height": 1200
            }
        )

        network_responses = []

        def handle_response(response):

            try:

                response_url = response.url.lower()

                if any(
                    term in response_url
                    for term in [
                        "price",
                        "quote",
                        "fuel",
                        "product",
                        "order",
                        "api",
                        "ajax",
                        "droplet"
                    ]
                ):

                    network_responses.append(
                        response
                    )

            except Exception:
                pass

        page.on(
            "response",
            handle_response
        )

        diagnostic = []

        try:

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000
            )

            page.wait_for_timeout(
                7000
            )

            # -------------------------------------------------
            # FIND ZIP INSIDE EVERY FRAME
            # -------------------------------------------------

            zip_box = None
            zip_frame = None

            for frame in page.frames:

                try:

                    inputs = frame.locator(
                        "input"
                    )

                    count = inputs.count()

                    for i in range(count):

                        candidate = inputs.nth(i)

                        try:

                            metadata = candidate.evaluate(
                                """
                                el => {
                                    let parentText = "";
                                    if (el.parentElement) {
                                        parentText =
                                            el.parentElement.innerText || "";
                                    }

                                    return {
                                        name: el.name || "",
                                        id: el.id || "",
                                        placeholder:
                                            el.placeholder || "",
                                        aria:
                                            el.getAttribute("aria-label") || "",
                                        type: el.type || "",
                                        parentText:
                                            parentText.substring(0, 500)
                                    };
                                }
                                """
                            )

                            combined = " ".join(
                                str(v)
                                for v in metadata.values()
                            ).lower()

                            if (
                                "zip code" in combined
                                or "zipcode" in combined
                                or "postal code" in combined
                                or "postal" in combined
                                or re.search(
                                    r"\bzip\b",
                                    combined
                                )
                            ):

                                zip_box = candidate
                                zip_frame = frame
                                break

                        except Exception:
                            continue

                except Exception:
                    continue

                if zip_box is not None:
                    break

            if zip_box is None:

                # Last-resort label lookup
                for frame in page.frames:

                    try:

                        label = frame.get_by_text(
                            "Zip Code",
                            exact=True
                        )

                        if label.count() > 0:

                            inputs = frame.locator(
                                "input"
                            )

                            if inputs.count() > 0:

                                zip_box = inputs.last
                                zip_frame = frame
                                break

                    except Exception:
                        continue

            if zip_box is None:

                raise RuntimeError(
                    f"{supplier_name} ZIP input not found"
                )

            # -------------------------------------------------
            # ENTER ZIP
            # -------------------------------------------------

            zip_box.fill(
                ZIP
            )

            # -------------------------------------------------
            # CHECK PRICE BUTTON
            # -------------------------------------------------

            check_button = None

            for selector in [
                'button:has-text("Check Price")',
                'button:has-text("Check price")',
                'button:has-text("Get Price")',
                'button:has-text("Get price")',
                'button:has-text("View Price")',
                'button:has-text("View price")',
                'button:has-text("Check")',
                'button:has-text("Price")',
                'input[type="submit"]',
            ]:

                try:

                    locator = zip_frame.locator(
                        selector
                    )

                    if locator.count() > 0:

                        check_button = locator.first
                        break

                except Exception:
                    continue

            if check_button is None:

                # Try buttons in the frame
                try:

                    buttons = zip_frame.locator(
                        "button"
                    )

                    if buttons.count() > 0:

                        check_button = buttons.last

                except Exception:
                    pass

            if check_button is None:

                raise RuntimeError(
                    f"{supplier_name} Check Price button not found"
                )

            check_button.click()

            page.wait_for_timeout(
                10000
            )

            # -------------------------------------------------
            # SEARCH FRAME TEXT
            # -------------------------------------------------

            for frame in page.frames:

                try:

                    body = clean_text(
                        frame.locator(
                            "body"
                        ).inner_text(
                            timeout=5000
                        )
                    )

                    if body:
                        diagnostic.append(body)

                    # Prefer exact 100-299 tier
                    price = extract_100_299_price(
                        body
                    )

                    if price is not None:

                        browser.close()

                        return (
                            price,
                            "ZIP-specific 100-299 gallon price"
                        )

                    price = extract_100_149_price(
                        body
                    )

                    if price is not None:

                        browser.close()

                        return (
                            price,
                            "ZIP-specific 100-149 gallon price"
                        )

                    price = extract_100_plus_price(
                        body
                    )

                    if price is not None:

                        browser.close()

                        return (
                            price,
                            "ZIP-specific 100+ gallon price"
                        )

                except Exception:
                    continue

            # -------------------------------------------------
            # SEARCH HTML
            # -------------------------------------------------

            for frame in page.frames:

                try:

                    html = frame.content()

                    html_text = clean_text(
                        html
                    )

                    price = extract_100_299_price(
                        html_text
                    )

                    if price is not None:

                        browser.close()

                        return (
                            price,
                            "ZIP-specific 100-299 gallon price"
                        )

                    price = extract_100_plus_price(
                        html_text
                    )

                    if price is not None:

                        browser.close()

                        return (
                            price,
                            "ZIP-specific 100+ gallon price"
                        )

                except Exception:
                    continue

            # -------------------------------------------------
            # NETWORK FALLBACK
            # -------------------------------------------------

            for response in network_responses:

                try:

                    content_type = (
                        response.headers.get(
                            "content-type",
                            ""
                        ).lower()
                    )

                    if (
                        "json" in content_type
                        or "text" in content_type
                        or "javascript" in content_type
                        or "html" in content_type
                    ):

                        response_text = response.text()

                        price = extract_100_299_price(
                            response_text
                        )

                        if price is not None:

                            browser.close()

                            return (
                                price,
                                "ZIP-specific 100-299 gallon price"
                            )

                        price = extract_100_plus_price(
                            response_text
                        )

                        if price is not None:

                            browser.close()

                            return (
                                price,
                                "ZIP-specific 100+ gallon price"
                            )

                except Exception:
                    continue

            print(
                f"\n----- {supplier_name.upper()} DIAGNOSTIC -----\n"
            )

            print(
                "\n\n".join(diagnostic)[:15000]
            )

            browser.close()

            return (
                None,
                "ZIP accepted, but price was not found."
            )

        except Exception as error:

            try:
                browser.close()
            except Exception:
                pass

            return (
                None,
                f"{supplier_name} quote failed: "
                + type(error).__name__
                + ": "
                + str(error)[:250]
            )


# =========================================================
# ANYTIME OIL
# =========================================================

def anytime_oil():

    return quote_page_100_plus(
        "https://anytime-oil.com/get-price/",
        "Anytime Oil"
    )


# =========================================================
# RIGHT ENERGY
# =========================================================

def right_energy():

    return quote_page_100_plus(
        "https://www.rightenergyct.com/get-price/",
        "Right Energy"
    )


# =========================================================
# INCREDIBLE OIL
# =========================================================

def incredible_oil():

    text = soup_text(
        "https://www.incredibleoil.com/home-heating-oil/"
    )

    price = extract_100_299_price(text)

    if price is not None:

        return (
            price,
            "Published 100-299 gallon price"
        )

    price = extract_100_149_price(text)

    if price is not None:

        return (
            price,
            "Published 100-149 gallon price"
        )

    raise RuntimeError(
        "Could not find Incredible Oil price"
    )


# =========================================================
# BETHANY FUEL
# =========================================================

def bethany_fuel():

    text = soup_text(
        "https://www.bethanyfuel.com/"
    )

    # Exact 100-299 tier
    patterns = [
        r"100\s*[-–—]\s*299\s*\|?\s*\$\s*(\d+\.\d{2,3})",
        r"100\s*[-–—]\s*299.{0,100}?\$\s*(\d+\.\d{2,3})",
        r"100\s*[-–—]\s*299\s*Gallons?.{0,100}?\$\s*(\d+\.\d{2,3})",
    ]

    price = extract_price(
        patterns,
        text
    )

    if price is not None:

        return (
            price,
            "Published 100-299 gallon homepage price"
        )

    # Today's price fallback
    price = extract_price(
        [
            r"TODAY'?S\s+PRICE\s*:?\s*\$\s*(\d+\.\d{2,3})",
            r"TODAY’?S\s+PRICE\s*:?\s*\$\s*(\d+\.\d{2,3})",
        ],
        text
    )

    if price is not None:

        return (
            price,
            "Published homepage 100-299 gallon price"
        )

    raise RuntimeError(
        "Could not find Bethany Fuel price"
    )


# =========================================================
# FJ BOIL
# =========================================================

def fj_boil():

    url = "https://www.fjboil.com/get-price/"

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        )

        page = browser.new_page(
            viewport={
                "width": 1440,
                "height": 1200
            }
        )

        network_responses = []

        def handle_response(response):

            try:

                if any(
                    term in response.url.lower()
                    for term in [
                        "price",
                        "quote",
                        "fuel",
                        "product",
                        "order",
                        "api",
                        "ajax",
                        "droplet"
                    ]
                ):

                    network_responses.append(
                        response
                    )

            except Exception:
                pass

        page.on(
            "response",
            handle_response
        )

        diagnostic = []

        try:

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000
            )

            page.wait_for_timeout(
                7000
            )

            # -------------------------------------------------
            # FIND FRAME CONTAINING ORDER FORM
            # -------------------------------------------------

            target_frame = None

            for frame in page.frames:

                try:

                    body = clean_text(
                        frame.locator(
                            "body"
                        ).inner_text(
                            timeout=3000
                        )
                    )

                    if (
                        "heating oil" in body.lower()
                        or "zip code" in body.lower()
                        or "check price" in body.lower()
                    ):

                        target_frame = frame
                        break

                except Exception:
                    continue

            if target_frame is None:
                target_frame = page.main_frame

            # -------------------------------------------------
            # SELECT HEATING OIL
            # -------------------------------------------------

            selected_oil = False

            selects = target_frame.locator(
                "select"
            )

            for i in range(
                selects.count()
            ):

                select = selects.nth(i)

                try:

                    options = select.locator(
                        "option"
                    )

                    for j in range(
                        options.count()
                    ):

                        option = options.nth(j)

                        option_text = clean_text(
                            option.inner_text()
                        )

                        if (
                            "heating oil"
                            in option_text.lower()
                        ):

                            value = option.get_attribute(
                                "value"
                            )

                            try:

                                if value:
                                    select.select_option(
                                        value=value
                                    )
                                else:
                                    select.select_option(
                                        label=option_text
                                    )

                                selected_oil = True

                                break

                            except Exception:
                                continue

                except Exception:
                    continue

                if selected_oil:
                    break

            # -------------------------------------------------
            # CUSTOM COMBOBOX FALLBACK
            # -------------------------------------------------

            if not selected_oil:

                try:

                    combos = target_frame.locator(
                        '[role="combobox"]'
                    )

                    for i in range(
                        combos.count()
                    ):

                        combo = combos.nth(i)

                        try:

                            combo.click()

                            target_frame.wait_for_timeout(
                                500
                            )

                            option = target_frame.locator(
                                '[role="option"]'
                            )

                            for j in range(
                                option.count()
                            ):

                                option_text = clean_text(
                                    option.nth(j).inner_text()
                                )

                                if (
                                    "heating oil"
                                    in option_text.lower()
                                ):

                                    option.nth(j).click()

                                    selected_oil = True

                                    break

                        except Exception:
                            continue

                        if selected_oil:
                            break

                except Exception:
                    pass

            # -------------------------------------------------
            # FIND ZIP
            # -------------------------------------------------

            zip_box = None

            inputs = target_frame.locator(
                "input"
            )

            for i in range(
                inputs.count()
            ):

                candidate = inputs.nth(i)

                try:

                    metadata = candidate.evaluate(
                        """
                        el => ({
                            name: el.name || "",
                            id: el.id || "",
                            placeholder: el.placeholder || "",
                            aria: el.getAttribute("aria-label") || "",
                            type: el.type || "",
                            parent:
                                el.parentElement
                                ? el.parentElement.innerText || ""
                                : ""
                        })
                        """
                    )

                    combined = " ".join(
                        str(v)
                        for v in metadata.values()
                    ).lower()

                    if (
                        "zip" in combined
                        or "postal" in combined
                    ):

                        zip_box = candidate
                        break

                except Exception:
                    continue

            if zip_box is None:

                raise RuntimeError(
                    "FJ Boil ZIP input not found"
                )

            zip_box.fill(
                ZIP
            )

            # -------------------------------------------------
            # GET PRICE
            # -------------------------------------------------

            price_button = None

            for selector in [
                'button:has-text("Get Price")',
                'button:has-text("Get price")',
                'button:has-text("Check Price")',
                'button:has-text("Check price")',
                'button:has-text("Check")',
                'button:has-text("Price")',
                'input[type="submit"]',
            ]:

                try:

                    locator = target_frame.locator(
                        selector
                    )

                    if locator.count() > 0:

                        price_button = locator.first
                        break

                except Exception:
                    continue

            if price_button is None:

                raise RuntimeError(
                    "FJ Boil Get Price button not found"
                )

            price_button.click()

            page.wait_for_timeout(
                10000
            )

            # -------------------------------------------------
            # SEARCH ALL FRAMES
            # -------------------------------------------------

            for frame in page.frames:

                try:

                    body = clean_text(
                        frame.locator(
                            "body"
                        ).inner_text(
                            timeout=5000
                        )
                    )

                    if body:
                        diagnostic.append(body)

                    price = extract_100_299_price(
                        body
                    )

                    if price is not None:

                        browser.close()

                        return (
                            price,
                            "ZIP-specific 100-299 gallon price"
                        )

                except Exception:
                    continue

            # -------------------------------------------------
            # NETWORK
            # -------------------------------------------------

            for response in network_responses:

                try:

                    response_text = response.text()

                    price = extract_100_299_price(
                        response_text
                    )

                    if price is not None:

                        browser.close()

                        return (
                            price,
                            "ZIP-specific 100-299 gallon price"
                        )

                except Exception:
                    continue

            print(
                "\n----- FJ BOIL DIAGNOSTIC -----\n"
            )

            print(
                "\n\n".join(diagnostic)[:15000]
            )

            browser.close()

            return (
                None,
                "Heating Oil selected and ZIP entered, but 100-299 price was not found."
            )

        except Exception as error:

            try:
                browser.close()
            except Exception:
                pass

            return (
                None,
                "FJ Boil quote failed: "
                + type(error).__name__
                + ": "
                + str(error)[:250]
            )


# =========================================================
# EASY OIL CT
# =========================================================

def easy_oil_ct():

    text = soup_text(
        "https://www.easyoilct.com/"
    )

    # Easy Oil currently uses:
    # Today's Price $5.69
    # 100 gallon minimum

    price = extract_price(
        [
            r"TODAY'?S\s+PRICE\s*:?\s*\$\s*(\d+\.\d{2,3})",
            r"TODAY’?S\s+PRICE\s*:?\s*\$\s*(\d+\.\d{2,3})",
            r"TODAY'?S\s+PRICE.{0,50}?\$\s*(\d+\.\d{2,3})",
        ],
        text
    )

    if price is not None:

        return (
            price,
            "Published 100-gallon minimum homepage price"
        )

    raise RuntimeError(
        "Could not find Easy Oil homepage price"
    )


# =========================================================
# G&G OIL CT
# =========================================================

def gg_oil_ct():

    return quote_page_100_plus(
        "https://ggoilct.com/get-price/",
        "GG Oil CT"
    )


# =========================================================
# OMNI ENERGY
# =========================================================

def omni_energy():

    text = soup_text(
        "https://myomnienergy.com/"
    )

    # IMPORTANT:
    #
    # Omni's homepage contains:
    #
    # Today's price is $5.69 per gallon
    #
    # but ALSO:
    #
    # 75 gallons for $438.00
    # 50 gallons for $312.00
    #
    # Therefore NEVER use a generic "100+ gallons" regex
    # here. It can accidentally grab $438.00.
    #

    price = extract_price(
        [
            r"TODAY'?S\s+PRICE\s+IS\s*\$\s*(\d+\.\d{2,3})\s+PER\s+GALLON",
            r"TODAY’?S\s+PRICE\s+IS\s*\$\s*(\d+\.\d{2,3})\s+PER\s+GALLON",
            r"TODAY'?S\s+PRICE.{0,30}?\$\s*(\d+\.\d{2,3})\s+PER\s+GALLON",
        ],
        text
    )

    if price is not None:

        return (
            price,
            "Published per-gallon homepage price"
        )

    # Secondary fallback:
    # Look for a price followed directly by "per gallon".

    price = extract_price(
        [
            r"\$\s*(\d+\.\d{2,3})\s+PER\s+GALLON",
        ],
        text
    )

    if price is not None:

        return (
            price,
            "Published per-gallon homepage price"
        )

    raise RuntimeError(
        "Could not find Omni Energy per-gallon homepage price"
    )


# =========================================================
# PURPLE FUELS
# =========================================================

def purple_fuels():

    # Purple Fuels has a dedicated pricing page.
    # This is much safer than scraping generic homepage text.

    text = soup_text(
        "https://www.purplefuels.com/heating-oil/pricing"
    )

    price = extract_price(
        [
            r"100\s*[-–—]\s*299\s*GAL.{0,150}?\$\s*(\d+\.\d{2,3})",
            r"100\s*[-–—]\s*299\s*GALLONS?.{0,150}?\$\s*(\d+\.\d{2,3})",
        ],
        text
    )

    if price is not None:

        return (
            price,
            "Published 100-299 gallon price"
        )

    raise RuntimeError(
        "Could not find Purple Fuels 100-299 gallon price"
    )


# =========================================================
# IT ENERGY
# =========================================================

def it_energy():

    text = soup_text(
        "https://itenergyllc.com/"
    )

    # IT Energy uses:
    # TODAY'S PRICE: $5.65
    # minimum of 100 gallons

    price = extract_price(
        [
            r"TODAY'?S\s+PRICE\s*:\s*\$\s*(\d+\.\d{2,3})",
            r"TODAY’?S\s+PRICE\s*:\s*\$\s*(\d+\.\d{2,3})",
            r"TODAY'?S\s+PRICE.{0,50}?\$\s*(\d+\.\d{2,3})",
        ],
        text
    )

    if price is not None:

        return (
            price,
            "Published homepage price; 100-gallon minimum"
        )

    raise RuntimeError(
        "Could not find IT Energy homepage price"
    )


# =========================================================
# FEDERAL OIL
# =========================================================

def federal_oil():

    text = soup_text(
        "https://federal-oil.com/"
    )

    # Use cash price.
    # Federal also publishes a higher credit-card price.

    price = extract_price(
        [
            r"CASH\s+PRICE\s*:\s*\$\s*(\d+\.\d{2,3})",
            r"CASH\s+PRICE.{0,50}?\$\s*(\d+\.\d{2,3})",
        ],
        text
    )

    if price is not None:

        return (
            price,
            "Published homepage cash price"
        )

    raise RuntimeError(
        "Could not find Federal Oil cash price"
    )


# =========================================================
# DIME OIL
# =========================================================

def dime_oil():

    text = soup_text(
        "https://www.dimeoilco.com/"
    )

    # Dime explicitly labels this as:
    # Today's Price: $X
    # Home Heating Oil for 150 gallons or more

    price = extract_price(
        [
            r"TODAY'?S\s+PRICE\s*:\s*\$\s*(\d+\.\d{2,3})",
            r"TODAY’?S\s+PRICE\s*:\s*\$\s*(\d+\.\d{2,3})",
        ],
        text
    )

    if price is not None:

        return (
            price,
            "Published 150+ gallon homepage price"
        )

    raise RuntimeError(
        "Could not find Dime Oil homepage price"
    )


# =========================================================
# SUPPLIER RUNNER
# =========================================================

def run_supplier(
    name,
    url,
    function
):

    result = {
        "name": name,
        "url": url,
        "price_per_gallon": None,
        "total_for_100_gallons": None,
        "note": "Unavailable"
    }

    try:

        price, note = function()

        if price is not None:

            result["price_per_gallon"] = round(
                price,
                3
            )

            result["total_for_100_gallons"] = round(
                price * GALLONS,
                2
            )

        result["note"] = note

    except Exception as error:

        result["note"] = (
            "Update failed: "
            + type(error).__name__
            + ": "
            + str(error)[:250]
        )

    return result


# =========================================================
# MAIN
# =========================================================

def main():

    suppliers = [

        # -------------------------------------------------
        # 1
        # -------------------------------------------------

        run_supplier(
            "First Fuel Oil",
            "https://www.firstfueloil.com/",
            first_fuel
        ),

        # -------------------------------------------------
        # 2
        # -------------------------------------------------

        run_supplier(
            "Phillips Oil & Propane",
            "https://phillipsoilllc.com/",
            phillips
        ),

        # -------------------------------------------------
        # 3
        # -------------------------------------------------

        run_supplier(
            "Curtiss Oil",
            "https://curtissoil.com/get-price/",
            curtiss
        ),

        # -------------------------------------------------
        # 4
        # -------------------------------------------------

        run_supplier(
            "Incredible Oil & Propane",
            "https://www.incredibleoil.com/home-heating-oil/",
            incredible_oil
        ),

        # -------------------------------------------------
        # 5
        # -------------------------------------------------

        run_supplier(
            "Anytime Oil",
            "https://anytime-oil.com/get-price/",
            anytime_oil
        ),

        # -------------------------------------------------
        # 6
        # -------------------------------------------------

        run_supplier(
            "Right Energy",
            "https://www.rightenergyct.com/get-price/",
            right_energy
        ),

        # -------------------------------------------------
        # 7
        # -------------------------------------------------

        run_supplier(
            "Bethany Fuel",
            "https://www.bethanyfuel.com/",
            bethany_fuel
        ),

        # -------------------------------------------------
        # 8
        # -------------------------------------------------

        run_supplier(
            "FJ Boil",
            "https://www.fjboil.com/get-price/",
            fj_boil
        ),

        # -------------------------------------------------
        # 9
        # -------------------------------------------------

        run_supplier(
            "Easy Oil CT",
            "https://www.easyoilct.com/",
            easy_oil_ct
        ),

        # -------------------------------------------------
        # 10
        # -------------------------------------------------

        run_supplier(
            "GG Oil CT",
            "https://ggoilct.com/get-price/",
            gg_oil_ct
        ),

        # -------------------------------------------------
        # 11
        # -------------------------------------------------

        run_supplier(
            "Omni Energy",
            "https://myomnienergy.com/",
            omni_energy
        ),

        # -------------------------------------------------
        # 12
        # -------------------------------------------------

        run_supplier(
            "Purple Fuels",
            "https://www.purplefuels.com/heating-oil/pricing",
            purple_fuels
        ),

        # -------------------------------------------------
        # 13
        # -------------------------------------------------

        run_supplier(
            "IT Energy",
            "https://itenergyllc.com/",
            it_energy
        ),

        # -------------------------------------------------
        # 14
        # -------------------------------------------------

        run_supplier(
            "Federal Oil",
            "https://federal-oil.com/",
            federal_oil
        ),

        # -------------------------------------------------
        # 15
        # -------------------------------------------------

        run_supplier(
            "Dime Oil",
            "https://www.dimeoilco.com/",
            dime_oil
        ),
    ]


    # =====================================================
    # SORT CHEAPEST FIRST
    # =====================================================

    suppliers.sort(
        key=lambda x: (
            x["price_per_gallon"] is None,
            x["price_per_gallon"]
            if x["price_per_gallon"] is not None
            else float("inf")
        )
    )


    # =====================================================
    # OUTPUT
    # =====================================================

    output = {
        "zip": ZIP,
        "gallons": GALLONS,
        "updated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "sources": suppliers
    }


    OUT.parent.mkdir(
        parents=True,
        exist_ok=True
    )


    OUT.write_text(
        json.dumps(
            output,
            indent=2
        ),
        encoding="utf-8"
    )


    print(
        json.dumps(
            output,
            indent=2
        )
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()