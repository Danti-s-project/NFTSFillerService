import asyncio
from typing import Optional

import aiohttp
import bs4


class Worker:
    """
    Worker для индексации коллекций NFT.

    Каждый объект этого класса привязан к конкретной коллекции NFT и занимается её индексацией
    всё время, пока работает сервер. Все инстансы управляются WorkerManager'ом 
    из backend.nfts.service.worker_manager.py.
    """

    BASE_URL = 'https://t.me/nft/'
    HOST = 'http://localhost:8000'

    class ParsedInfo:
        """
        Структура данных для хранения спаршенной информации о NFT.

        Attributes:
            owner: Имя пользователя владельца NFT.
            model: Название модели NFT.
            backdrop: Название фона NFT.
            symbol: Название символа NFT.
        """

        def __init__(self):
            self.owner: str = ""
            self.model: str = ""
            self.backdrop: str = ""
            self.symbol: str = ""

    def __init__(self, collection_name: str):
        """
        Инициализирует Worker для указанной коллекции NFT.

        Args:
            collection_name: Коллекция NFT для индексации.
        """
        self.__collection: str = collection_name
        self.__serve_task: Optional[asyncio.Task] = None

    def run(self):
        """
        Запускает процесс индексации коллекции NFT.

        Создаёт асинхронную задачу в текущем event loop для обработки коллекции.
        """
        loop = asyncio.get_event_loop()
        self.__serve_task = loop.create_task(self.__serve())

    async def __serve(self):
        """
        Основной цикл worker'а, в котором собирается информация о NFT.

        Цикл продолжается до тех пор, пока не будут проиндексированы все NFT в коллекции.
        """

        async with aiohttp.ClientSession() as session:
            async with session.get(f"{Worker.HOST}/api/v1/collections/{self.__collection}/") as response:
                collection_data = await response.json()
                while collection_data["indexed"] < collection_data["quantity"]:
                    await self.__request()

    async def __request(self):
        """
        Выполняет HTTP запрос к странице с информацией о NFT и обрабатывает ответ.

        Если ответ успешный (код 200), данные парсятся и сохраняются в базу данных.
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(await self.__get_next_url()) as response:
                if response.status == 200:
                    await self.__write_to_database(self.__parse_info(await response.text()))

    async def __get_next_url(self) -> str:
        """
        Формирует URL для следующего NFT, требующего индексации.

        Returns:
            URL страницы с информацией о следующем NFT в коллекции.
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{Worker.HOST}/api/v1/collections/{self.__collection}/") as response:
                collection_data = await response.json()
                return f"{Worker.BASE_URL}{self.__collection}-{collection_data["indexed"] + 1}"

    async def __get_or_create_related(self, django_model: str, value: str) -> None:
        """
            param: django model: Название искомого свойства
            param: value: значение для свойства
        """

        async with aiohttp.ClientSession() as session:
            async with session.get(f"{Worker.HOST}/api/v1/{django_model}/{value}/") as response:
                if response.status != 200:
                    async with session.post(f"{Worker.HOST}/api/v1/{django_model}/", json={"name": value}):
                        pass

    async def __write_to_database(self, nft_info: ParsedInfo) -> None:
        """
        Сохраняет информацию о NFT в базу данных.

        Создаёт новый объект NFT и связывает его с соответствующими моделями
        (владелец, модель, фон, символ). Если какая-либо из связанных моделей
        отсутствует в базе данных, она будет создана.

        Args:
            nft_info: Объект с данными о NFT, полученный при парсинге.
        """

        request_json = {}

        if nft_info.owner:
            request_json["owner"] = await self.__get_or_create_related("owner", nft_info.owner)
        request_json["model"] = await self.__get_or_create_related("model", nft_info.model)
        request_json["backdrop"] = await self.__get_or_create_related("backdrop", nft_info.backdrop)
        request_json["symbol"] = await self.__get_or_create_related("symbol", nft_info.symbol)

        async with aiohttp.ClientSession() as session:
            async with session.post(f"{Worker.HOST}/api/v1/nft/", json=request_json):
                pass

        # Увеличиваем счётчик проиндексированных NFT

        async with aiohttp.ClientSession() as session:
            async with session.get(f"{Worker.HOST}/api/v1/collections/{self.__collection}/") as response:
                collection_data = await response.json()
                async with session.patch(f"{Worker.HOST}/api/v1/collections/{self.__collection}/",
                                         json={"quantity": collection_data["indexed"] + 1}):
                    pass

    def __parse_info(self, content: str) -> ParsedInfo:
        """
        Парсит HTML страницу с информацией о NFT и собирает ParsedInfo объект с информацией
        return: Наполненный объект ParsedInfo
        """

        # Инициализируем нужные объекты
        info = Worker.ParsedInfo()
        soup: bs4.BeautifulSoup = bs4.BeautifulSoup(content, "lxml")

        # Парсим страницу и записываем в информацию в ParsedInfo
        table = soup.find("table", class_="table tgme_gift_table").find("tbody")

        for child in table.find_all("tr"):
            nft_property = child.find('th').text
            value_element = child.find('td')

            match nft_property:
                case "Owner":
                    owner_url = value_element.find("a")
                    if owner_url:
                        info.owner = owner_url.text
                case "Model":
                    info.model = value_element.text
                case "Backdrop":
                    info.backdrop = value_element.text
                case "Symbol":
                    info.symbol = value_element.text

        return info
