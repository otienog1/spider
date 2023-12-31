import time
from urllib.parse import urljoin, urlparse
from selenium import webdriver
from selenium.common import (
    TimeoutException,
    StaleElementReferenceException,
    NoSuchElementException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def parse_url(url):
    parsed_url = urlparse(url)
    scheme = parsed_url.scheme
    netloc = parsed_url.netloc
    path = parsed_url.path
    if path.endswith(".html"):
        parts = path.rsplit(".", 1)
        if len(parts) == 1 or "en-gb" not in parts[0]:
            path = f"{parts[0]}.en-gb.html"

        return urljoin(f"{scheme}://{netloc}", path)


def init_driver():
    options = webdriver.ChromeOptions()
    options.add_experimental_option("detach", True)
    return webdriver.Chrome(
        options=options,
        service=ChromeService(
            ChromeDriverManager().install(), chrome_driver_version="latest"
        ),
    )


class WebScraper:
    def __init__(self, url):
        self.url = url
        self.driver = init_driver()
        self._link_list = []
        self._crawled_links = []

        self._link_list.extend(url)

    @property
    def link_list(self):
        return self._link_list

    @property
    def crawled_links(self):
        return self._crawled_links

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.driver.quit()

    def scrape_page(self, url=None):
        if url is None:
            url = self.url

        with self.driver as driver:
            driver.get(url)

            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "bui-carousel__inner"))
            )

            titles = driver.find_elements(By.CSS_SELECTOR, ".hp__hotel-title.pp-header")
            summaries = driver.find_elements(
                By.CSS_SELECTOR, ".hotel_description_review_display"
            )

            for title in titles:
                title = title.find_element(By.CSS_SELECTOR, "h2")
                if title:
                    print(f"Title: {title.text.strip()}")

            for summary in summaries:
                summary = summary.find_element(
                    By.CSS_SELECTOR, ".a53cbfa6de.b3efd73f69"
                )
                if summary:
                    print(f"Summary: {summary.text.strip()}")
                    print("-----------")

            carousel_div = driver.find_element(By.CLASS_NAME, "bui-carousel__inner")
            links = carousel_div.find_elements(By.TAG_NAME, "a")

            new_links = [
                link.get_attribute("href")
                for link in links
                if link.get_attribute("href")
            ]
            new_links = [
                parse_url(link)
                for link in new_links
                if parse_url(link) and parse_url(link) not in self._link_list
            ]

            print("Collected Links:")
            for link in new_links:
                print(link)

            self._link_list.extend(new_links)
            self._crawled_links.append(parse_url(url))

            return new_links

    def scrape_continent(self, url):
        with self.driver as driver:
            driver.get(url)

            try:
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located(
                        (By.CLASS_NAME, "bui-carousel__item")
                    )
                )

                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located(
                        (By.CLASS_NAME, "bui-list__description-title")
                    )
                )

                # Find all spans with class 'bui-list__description-title
                description_spans = driver.find_elements(
                    By.CLASS_NAME, "bui-list__description-title"
                )

                # Find all carousel items
                carousel_items = driver.find_elements(By.CLASS_NAME, "bui-carousel__item")

                # Collect href attributes of links within carousel items
                href_list = []
                for item in carousel_items:
                    links = item.find_elements(By.TAG_NAME, 'a')
                    href_list.extend(
                        parse_url(link.get_attribute('href')) for link in links if link.get_attribute('href')
                    )

                for span in description_spans:
                    link = span.find_element(By.TAG_NAME, 'a')
                    href = parse_url(link.get_attribute('href'))
                    if href:
                        href_list.append(href)

                # Add the collected href attributes to the link list
                self._link_list.extend(href_list)

                print(href_list)

                return href_list

            except TimeoutException:
                print(
                    f"TimeoutException: Element 'bui-carousel__item' not found on {url}. Moving to the next link."
                )
                return []
            except StaleElementReferenceException:
                print(
                    f"StaleElementReferenceException: Element 'summary' is stale on {url}. Moving to the next iteration."
                )
                return []

            except NoSuchElementException:
                print(
                    f"NoSuchElementException: Element 'bui-carousel__inner' not found on {url}. Moving to the next "
                    f"iteration."
                )
                return []

    def open_and_scrape_in_new_tab(self):
        with self.driver as driver:
            for url in self._link_list:
                print(f"Link List: {self._link_list}")
                print(f"Link List Length: - {len(self._link_list)}")
                print(f"Crawled Link Length: - {len(self._crawled_links)}")

                current_url = parse_url(url)

                if current_url not in self._crawled_links:
                    # Open the link in a new tab
                    driver.execute_script(f"window.open('{current_url}', '_blank');")
                    # Add a wait of 2 seconds
                    time.sleep(2)
                    # Switch to the new tab
                    driver.switch_to.window(driver.window_handles[-1])
                    print(f"Crawled Link: {self._crawled_links}")

                    try:
                        # Scraping logic
                        WebDriverWait(driver, 20).until(
                            EC.presence_of_element_located(
                                (By.CLASS_NAME, "bui-carousel__inner")
                            )
                        )

                        titles = driver.find_elements(
                            By.CSS_SELECTOR, ".hp__hotel-title.pp-header"
                        )
                        summaries = driver.find_elements(
                            By.CSS_SELECTOR, ".hotel_description_review_display"
                        )

                        for title in titles:
                            title = title.find_element(By.CSS_SELECTOR, "h2")
                            if title:
                                print(f"Title: {title.text.strip()}")

                        for summary in summaries:
                            summary = summary.find_element(
                                By.CSS_SELECTOR, ".a53cbfa6de.b3efd73f69"
                            )
                            if summary:
                                print(f"Summary: {summary.text.strip()}")
                                print("-----------")

                        # Find the div with class 'bui-carousel__inner' in the new tab
                        carousel_div = driver.find_element(
                            By.CLASS_NAME, "bui-carousel__inner"
                        )

                        # Find all links within the div
                        new_links = carousel_div.find_elements(By.TAG_NAME, "a")

                        # Collect href attributes into the original list
                        for new_link in new_links:
                            new_href = parse_url(new_link.get_attribute("href"))
                            if (
                                    new_href
                                    and new_href not in self._link_list
                                    and parse_url(new_href) not in self._crawled_links
                            ):
                                print(f"New Link: {new_href}")
                                self._link_list.append(new_href)

                    except TimeoutException:
                        print(
                            f"TimeoutException: Element 'bui-carousel__inner' not found on {current_url}. Moving to the next link.")
                        continue

                    except StaleElementReferenceException:
                        print(
                            f"StaleElementReferenceException: Element 'summary' is stale on {current_url}. Moving to the next iteration.")
                        continue

                    except NoSuchElementException:
                        print(
                            f"NoSuchElementException: Element 'bui-carousel__inner' not found on {current_url}. Moving to the next iteration.")
                        continue

                    finally:
                        # Close the new tab
                        driver.close()
                        # Switch back to the original tab
                        driver.switch_to.window(driver.window_handles[0])

                        # Append the current URL from the crawled link list
                    self._crawled_links.append(parse_url(current_url))

                    # Remove the current URL from the link list since it has been processed
                    # self._link_list.remove(current_url)


if __name__ == "__main__":
    target_url = [
        "https://www.booking.com/hotel/ke/jukes-serene-westlands-villa.en-gb.html",
        "https://www.booking.com/hotel/ke/fairmont-mara-safari-club.en-gb.html",
        "https://www.booking.com/hotel/ke/tune.en-gb.html",
        "https://www.booking.com/hotel/ke/the-lazizi-premiere-nairobi.en-gb.html",
        "https://www.booking.com/hotel/ke/kandiz-exquisite.en-gb.html",
        "https://www.booking.com/hotel/tz/breezes-beach-club-and-spa.en-gb.html",
        "https://www.booking.com/hotel/ae/orchid-dubai123.en-gb.html",
        'https://www.booking.com/hotel/ke/radisson-blu-nairobi.en-gb.html',
        'https://www.booking.com/hotel/ke/the-sands-at-nomad.en-gb.html',
        'https://www.booking.com/hotel/ke/coral-beach-resort.en-gb.html',
        'https://www.booking.com/hotel/ke/diani-reef-beach-resort-spa.en-gb.html',
        'https://www.booking.com/hotel/ke/jacaranda-indian-ocean-beach-resort.en-gb.html',
        'https://www.booking.com/hotel/ke/best-western-plus-creekside.en-gb.html',
        'https://www.booking.com/hotel/ke/sarova-whitesands-beach-resort-amp-spa.en-gb.html',
        'https://www.booking.com/hotel/ke/englishpoint.en-gb.html',
        'https://www.booking.com/hotel/ke/prideinn-links-road.en-gb.html',
        'https://www.booking.com/hotel/ke/bahari-beach.en-gb.html',
        'https://www.booking.com/hotel/ke/tribe-nairobi.en-gb.html',
        'https://www.booking.com/hotel/ke/the-lazizi-premiere-nairobi.en-gb.html',
        'https://www.booking.com/hotel/ke/the-sands-at-nomad.en-gb.html',
        'https://www.booking.com/hotel/ke/diani-reef-beach-resort-spa.en-gb.html',
        'https://www.booking.com/hotel/ke/prideinn-diani-diani-beach5.en-gb.html',
        'https://www.booking.com/hotel/ke/blue-marlin-beach-resort.en-gb.html',
        'https://www.booking.com/hotel/ke/flamboyant-bed-and-breakfast.en-gb.html',
        'https://www.booking.com/hotel/ke/aqua-resort.en-gb.html',
        'https://www.booking.com/hotel/tz/arusha-coffee-lodge.en-gb.html',
        'https://www.booking.com/hotel/tz/gran-melia-arusha.en-gb.html',
        'https://www.booking.com/hotel/tz/east-african.en-gb.html',
        'https://www.booking.com/hotel/tz/kibo-palace.en-gb.html',
        'https://www.booking.com/hotel/tz/tulia-amp-spa.en-gb.html',
        'https://www.booking.com/hotel/tz/mount-meru-arusha.en-gb.html',
        'https://www.booking.com/hotel/ke/amboseli-sopa-lodge.en-gb.html',
        'https://www.booking.com/hotel/ke/kilima-safari-camp.en-gb.html',
        'https://www.booking.com/hotel/ke/amboseli-serena-safari-lodge.en-gb.html',
        'https://www.booking.com/hotel/ke/little-amanya-camp-amboseli-national-park.en-gb.html',
        'https://www.booking.com/hotel/ke/kibo-safari-camp.en-gb.html',
        'https://www.booking.com/hotel/ke/tulia-amboseli-safari-camp.en-gb.html',
        'https://www.booking.com/hotel/ke/tawi-lodge.en-gb.html',
        'https://www.booking.com/hotel/tz/kilindi-zanzibar-nungwi.en-gb.html',
        'https://www.booking.com/hotel/tz/zuri-zanzibar.en-gb.html',
        'https://www.booking.com/hotel/tz/the-manor-at-ngorongoro.en-gb.html',
    ]
    continent = 'https://www.booking.com/continent/africa.en-gb.html'

    with WebScraper(target_url) as scraper:
        # scraper.open_and_scrape_in_new_tab()
        scraper.scrape_continent(continent)
