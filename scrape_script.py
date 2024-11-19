import asyncio
import json
import random
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Union
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import aiohttp
import yaml
from pydantic import BaseModel, HttpUrl
from selenium import webdriver
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    NoSuchElementException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import logging
from concurrent.futures import ThreadPoolExecutor
import backoff

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("hotel_crawler.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


# Configuration Models
class ScraperConfig(BaseModel):
    max_retries: int = 3
    retry_delay: float = 1.0
    concurrent_requests: int = 5
    request_timeout: int = 30
    max_pages_per_hotel: int = 100
    user_agents: List[str]
    output_directory: str
    respect_robots_txt: bool = True
    rate_limit_delay: tuple[float, float] = (2.0, 5.0)


class HotelWebsiteConfig(BaseModel):
    name: str
    base_url: HttpUrl
    selectors: Dict[str, str]
    required_cookies: Dict[str, str] = {}
    headers: Dict[str, str] = {}


# Data Models
@dataclass
class HotelAmenity:
    category: str
    name: str
    description: Optional[str] = None
    is_available: bool = True


@dataclass
class HotelRoom:
    name: str
    description: Optional[str]
    amenities: List[HotelAmenity]
    max_occupancy: Optional[int]
    price_range: Optional[tuple[float, float]]


@dataclass
class Hotel:
    name: str
    url: str
    description: Optional[str]
    address: Optional[str]
    rating: Optional[float]
    review_count: Optional[int]
    amenities: List[HotelAmenity]
    rooms: List[HotelRoom]
    images: List[str]
    crawled_at: datetime
    source_website: str


class RateLimiter:
    def __init__(self, min_delay: float, max_delay: float):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.last_request_time: Dict[str, float] = {}

    async def wait(self, domain: str):
        """Implement rate limiting per domain"""
        if domain in self.last_request_time:
            elapsed = time.time() - self.last_request_time[domain]
            delay = random.uniform(self.min_delay, self.max_delay)
            if elapsed < delay:
                await asyncio.sleep(delay - elapsed)
        self.last_request_time[domain] = time.time()


class RobotsChecker:
    def __init__(self):
        self._parsers: Dict[str, RobotFileParser] = {}

    @backoff.on_exception(
        backoff.expo, (aiohttp.ClientError, asyncio.TimeoutError), max_tries=3
    )
    async def can_fetch(self, url: str, user_agent: str) -> bool:
        parsed_url = urlparse(url)
        domain = f"{parsed_url.scheme}://{parsed_url.netloc}"

        if domain not in self._parsers:
            parser = RobotFileParser()
            parser.set_url(f"{domain}/robots.txt")

            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(f"{domain}/robots.txt") as response:
                        if response.status == 200:
                            content = await response.text()
                            parser.parse(content.splitlines())
                except Exception as e:
                    logger.warning(f"Could not fetch robots.txt for {domain}: {e}")
                    return True

            self._parsers[domain] = parser

        return self._parsers[domain].can_fetch(user_agent, url)


class HotelScraper:
    def __init__(
        self, config: ScraperConfig, website_configs: List[HotelWebsiteConfig]
    ):
        self.config = config
        self.website_configs = {config.name: config for config in website_configs}
        self.rate_limiter = RateLimiter(
            min_delay=config.rate_limit_delay[0], max_delay=config.rate_limit_delay[1]
        )
        self.robots_checker = RobotsChecker()
        self.seen_urls: Set[str] = set()
        self._setup_output_directory()

    def _setup_output_directory(self):
        self.output_dir = Path(self.config.output_directory)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _get_driver(self) -> WebDriver:
        """Initialize WebDriver with rotating user agents"""
        options = webdriver.ChromeOptions()
        options.add_argument(f"user-agent={random.choice(self.config.user_agents)}")
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        return webdriver.Chrome(
            options=options, service=ChromeService(ChromeDriverManager().install())
        )

    async def _extract_hotel_data(
        self, driver: WebDriver, url: str, website_config: HotelWebsiteConfig
    ) -> Optional[Hotel]:
        """Extract hotel data using provided selectors"""
        try:
            await self.rate_limiter.wait(urlparse(url).netloc)

            driver.get(url)
            WebDriverWait(driver, self.config.request_timeout).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, website_config.selectors["hotel_name"])
                )
            )

            # Extract basic hotel information
            name = driver.find_element(
                By.CSS_SELECTOR, website_config.selectors["hotel_name"]
            ).text.strip()

            description = None
            try:
                description = driver.find_element(
                    By.CSS_SELECTOR, website_config.selectors["description"]
                ).text.strip()
            except NoSuchElementException:
                pass

            # Extract amenities
            amenities = []
            amenity_elements = driver.find_elements(
                By.CSS_SELECTOR, website_config.selectors["amenities"]
            )
            for element in amenity_elements:
                try:
                    category = element.get_attribute("data-category")
                    name = element.text.strip()
                    amenities.append(
                        HotelAmenity(category=category or "general", name=name)
                    )
                except Exception as e:
                    logger.warning(f"Error extracting amenity: {e}")

            # Extract rooms
            rooms = []
            room_elements = driver.find_elements(
                By.CSS_SELECTOR, website_config.selectors["rooms"]
            )
            for element in room_elements:
                try:
                    room = self._extract_room_data(element, website_config)
                    if room:
                        rooms.append(room)
                except Exception as e:
                    logger.warning(f"Error extracting room data: {e}")

            return Hotel(
                name=name,
                url=url,
                description=description,
                address=None,  # Add address extraction
                rating=None,  # Add rating extraction
                review_count=None,  # Add review count extraction
                amenities=amenities,
                rooms=rooms,
                images=[],  # Add image extraction
                crawled_at=datetime.now(),
                source_website=website_config.name,
            )

        except Exception as e:
            logger.error(f"Error extracting hotel data from {url}: {e}")
            return None

    def _extract_room_data(
        self, element: WebElement, website_config: HotelWebsiteConfig
    ) -> Optional[HotelRoom]:
        """Extract room data from a room element"""
        try:
            name = element.find_element(
                By.CSS_SELECTOR, website_config.selectors["room_name"]
            ).text.strip()

            description = None
            try:
                description = element.find_element(
                    By.CSS_SELECTOR, website_config.selectors["room_description"]
                ).text.strip()
            except NoSuchElementException:
                pass

            # Extract room amenities
            amenities = []
            amenity_elements = element.find_elements(
                By.CSS_SELECTOR, website_config.selectors["room_amenities"]
            )
            for amenity_element in amenity_elements:
                amenities.append(
                    HotelAmenity(category="room", name=amenity_element.text.strip())
                )

            return HotelRoom(
                name=name,
                description=description,
                amenities=amenities,
                max_occupancy=None,  # Add occupancy extraction
                price_range=None,  # Add price range extraction
            )

        except Exception as e:
            logger.warning(f"Error extracting room data: {e}")
            return None

    async def save_hotel_data(self, hotel: Hotel):
        """Save hotel data to JSON file"""
        output_file = self.output_dir / f"{hotel.name}_{hotel.source_website}.json"
        with output_file.open("w", encoding="utf-8") as f:
            json.dump(asdict(hotel), f, indent=2, default=str)

    async def crawl_hotel(self, url: str, website_name: str):
        """Crawl a single hotel website"""
        if url in self.seen_urls:
            return

        self.seen_urls.add(url)
        website_config = self.website_configs[website_name]

        if self.config.respect_robots_txt:
            can_fetch = await self.robots_checker.can_fetch(
                url, random.choice(self.config.user_agents)
            )
            if not can_fetch:
                logger.info(f"Robots.txt disallows crawling {url}")
                return

        driver = None
        try:
            driver = self._get_driver()
            hotel_data = await self._extract_hotel_data(driver, url, website_config)

            if hotel_data:
                await self.save_hotel_data(hotel_data)
                logger.info(
                    f"Successfully crawled and saved data for {hotel_data.name}"
                )

        except Exception as e:
            logger.error(f"Error crawling {url}: {e}")

        finally:
            if driver:
                driver.quit()

    async def crawl_hotels(self, urls: List[str], website_name: str):
        """Crawl multiple hotel websites concurrently"""
        sem = asyncio.Semaphore(self.config.concurrent_requests)

        async def bounded_crawl(url: str):
            async with sem:
                await self.crawl_hotel(url, website_name)

        await asyncio.gather(*[bounded_crawl(url) for url in urls])


def load_config(config_path: str) -> tuple[ScraperConfig, List[HotelWebsiteConfig]]:
    """Load configuration from YAML file"""
    with open(config_path) as f:
        config_data = yaml.safe_load(f)

    scraper_config = ScraperConfig(**config_data["scraper"])
    website_configs = [
        HotelWebsiteConfig(**website_data) for website_data in config_data["websites"]
    ]

    return scraper_config, website_configs


if __name__ == "__main__":
    # Example configuration
    config_data = {
        "scraper": {
            "max_retries": 3,
            "retry_delay": 1.0,
            "concurrent_requests": 5,
            "request_timeout": 30,
            "max_pages_per_hotel": 100,
            "user_agents": [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                # Add more user agents...
            ],
            "output_directory": "hotel_data",
            "respect_robots_txt": True,
            "rate_limit_delay": (2.0, 5.0),
        },
        "websites": [
            {
                "name": "booking",
                "base_url": "https://www.booking.com",
                "selectors": {
                    "hotel_name": ".hp__hotel-title h2",
                    "description": ".hotel_description_review_display .a53cbfa6de.b3efd73f69",
                    "amenities": ".hotel-facilities__list li",
                    "rooms": ".hprt-table tr:not(.hprt-table-header-row)",
                    "room_name": ".hprt-roomtype-icon-link",
                    "room_description": ".hprt-facilities-facility",
                    "room_amenities": ".hprt-facilities-facility",
                },
            }
            # Add more website configurations...
        ],
    }

    # Initialize and run the scraper
    async def main():
        scraper_config = ScraperConfig(**config_data["scraper"])
        website_configs = [
            HotelWebsiteConfig(**website_data)
            for website_data in config_data["websites"]
        ]

        scraper = HotelScraper(scraper_config, website_configs)

        target_urls = [
            "https://www.booking.com/hotel/ke/jukes-serene-westlands-villa.en-gb.html",
            # Add more URLs...
        ]

        await scraper.crawl_hotels(target_urls, "booking")

    asyncio.run(main())
