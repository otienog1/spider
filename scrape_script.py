import time
from urllib.parse import urljoin, urlparse
from selenium import webdriver
from selenium.common import TimeoutException, StaleElementReferenceException
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
    if path.endswith('.html'):
        parts = path.rsplit('.', 1)
        if len(parts) == 1 or 'en-gb' not in parts[0]:
            path = f"{parts[0]}.en-gb.html"

        return urljoin(f'{scheme}://{netloc}', path)


def init_driver():
    options = webdriver.ChromeOptions()
    options.add_experimental_option("detach", True)
    return webdriver.Chrome(options=options,
                            service=ChromeService(ChromeDriverManager().install(), chrome_driver_version="latest"
                                                  ))


class WebScraper:
    def __init__(self, url):
        self.url = url
        self.driver = init_driver()
        self._link_list = [url]
        self._crawled_links = []

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
                EC.presence_of_element_located((By.CLASS_NAME, 'bui-carousel__inner'))
            )

            titles = driver.find_elements(By.CSS_SELECTOR, '.hp__hotel-title.pp-header')
            summaries = driver.find_elements(By.CSS_SELECTOR, '.hotel_description_review_display')

            for title in titles:
                title = title.find_element(By.CSS_SELECTOR, 'h2')
                if title:
                    print(f"Title: {title.text.strip()}")

            for summary in summaries:
                summary = summary.find_element(By.CSS_SELECTOR, '.a53cbfa6de.b3efd73f69')
                if summary:
                    print(f"Summary: {summary.text.strip()}")
                    print("-----------")

            carousel_div = driver.find_element(By.CLASS_NAME, 'bui-carousel__inner')
            links = carousel_div.find_elements(By.TAG_NAME, 'a')

            new_links = [link.get_attribute('href') for link in links if link.get_attribute('href')]
            new_links = [parse_url(link) for link in new_links if
                         parse_url(link) and parse_url(link) not in self._link_list]

            print("Collected Links:")
            for link in new_links:
                print(link)

            self._link_list.extend(new_links)
            self._crawled_links.append(parse_url(url))

            return new_links

    def open_and_scrape_in_new_tab(self):
        with self.driver as driver:
            while self._link_list:
                print(f"Link List: {self._link_list}")
                current_url = parse_url(self._link_list.pop(0))
                if current_url not in self._crawled_links:
                    # Open the link in a new tab
                    driver.execute_script(f"window.open('{current_url}', '_blank');")
                    # Add a wait of 2 seconds
                    time.sleep(2)
                    # Switch to the new tab
                    driver.switch_to.window(driver.window_handles[-1])
                    print(f"Crawled Link: {self._crawled_links}")

                    try:
                        print("Before WebDriverWait")

                        WebDriverWait(driver, 20).until(
                            EC.presence_of_element_located((By.CLASS_NAME, 'bui-carousel__inner'))
                        )

                        print("After WebDriverWait")

                        titles = driver.find_elements(By.CSS_SELECTOR, '.hp__hotel-title.pp-header')
                        summaries = driver.find_elements(By.CSS_SELECTOR, '.hotel_description_review_display')

                        for title in titles:
                            title = title.find_element(By.CSS_SELECTOR, 'h2')
                            if title:
                                print(f"Title: {title.text.strip()}")

                        for summary in summaries:
                            summary = summary.find_element(By.CSS_SELECTOR, '.a53cbfa6de.b3efd73f69')
                            if summary:
                                print(f"Summary: {summary.text.strip()}")
                                print("-----------")

                        # Find the div with class 'bui-carousel__inner' in the new tab
                        carousel_div = driver.find_element(By.CLASS_NAME, 'bui-carousel__inner')

                        # Find all links within the div
                        new_links = carousel_div.find_elements(By.TAG_NAME, 'a')

                        # Collect href attributes into the original list
                        for new_link in new_links:
                            new_href = parse_url(new_link.get_attribute('href'))
                            if new_href and new_href not in self._link_list and parse_url(
                                    new_href) not in self._crawled_links:
                                print(f"New Link: {new_href}")
                                self._link_list.append(new_href)

                        # Add the current URL to crawled links
                        self._crawled_links.append(parse_url(current_url))

                    except TimeoutException:
                        # Handle the TimeoutException (element not found) and proceed to the next link
                        print(
                            f"TimeoutException: Element 'bui-carousel__inner' not found on {current_url}. Moving to the next link.")
                        continue

                    except StaleElementReferenceException:
                        # Handle the StaleElementReferenceException and proceed to the next iteration
                        print(
                            f"StaleElementReferenceException: Element 'summary' is stale on {current_url}. Moving to the next iteration.")
                        continue

                    finally:
                        # Close the new tab
                        driver.close()
                        # Switch back to the original tab
                        driver.switch_to.window(driver.window_handles[0])


if __name__ == "__main__":
    # target_url = 'https://www.booking.com/hotel/ke/jukes-serene-westlands-villa.en-gb.html'
    # target_url = 'https://www.booking.com/hotel/ke/fairmont-mara-safari-club.en-gb.html'
    target_url = 'https://www.booking.com/hotel/ke/tune.en-gb.html'
    # target_url = 'https://www.booking.com/hotel/ke/the-lazizi-premiere-nairobi.en-gb.html'
    # target_url = 'https://www.booking.com/hotel/ke/kandiz-exquisite.en-gb.html'
    # target_url = 'https://www.booking.com/hotel/tz/breezes-beach-club-and-spa.en-gb.html'
    # target_url = 'https://www.booking.com/hotel/ae/orchid-dubai123.html'

    with WebScraper(target_url) as scraper:
        scraper.open_and_scrape_in_new_tab()
