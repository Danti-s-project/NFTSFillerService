import asyncio
from typing import Optional

import aiohttp
import bs4

from nfts.models import NFTCollection, NFT, NFTOwner, NFTSymbol, NFTModel, NFTBackdrop


class Worker:
    """
    Worker для индексации коллекций NFT.

    Каждый объект этого класса привязан к конкретной коллекции NFT и занимается её индексацией
    всё время, пока работает сервер. Все инстансы управляются WorkerManager'ом 
    из backend.nfts.service.worker_manager.py.
    """

    BASE_URL = 'https://t.me/nft/'

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

    def __init__(self, collection: NFTCollection):
        """
        Инициализирует Worker для указанной коллекции NFT.

        Args:
            collection: Коллекция NFT для индексации.
        """
        self.__collection: NFTCollection = collection
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
        while self.__collection.indexed < self.__collection.quantity:
            await self.__request()

    async def __request(self):
        """
        Выполняет HTTP запрос к странице с информацией о NFT и обрабатывает ответ.

        Если ответ успешный (код 200), данные парсятся и сохраняются в базу данных.
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(self.__get_next_url()) as response:
                if response.status == 200:
                    await self.__write_to_database(self.__parse_info(await response.text()))

    def __get_next_url(self) -> str:
        """
        Формирует URL для следующего NFT, требующего индексации.

        Returns:
            URL страницы с информацией о следующем NFT в коллекции.
        """
        return f"{Worker.BASE_URL}{self.__collection.name}-{self.__collection.indexed + 1}"

    async def __get_or_create_related(self, django_model, name: str):
        """
        Возвращает инстанс *django_model* по имени *name*

        Ищет в модели *django_model* объект с именем *name*
        Если его нет, то создает новый объект с именем *name* и сохраняет в базе данных

        return: django_model instance
        """
        instance = await django_model.objects.filter(name=name).afirst()
        if not instance:
            instance = django_model(name=name)
            await instance.asave()
        return instance

    async def __write_to_database(self, nft_info: ParsedInfo) -> None:
        """
        Сохраняет информацию о NFT в базу данных.

        Создаёт новый объект NFT и связывает его с соответствующими моделями
        (владелец, модель, фон, символ). Если какая-либо из связанных моделей
        отсутствует в базе данных, она будет создана.

        Args:
            nft_info: Объект с данными о NFT, полученный при парсинге.
        """
        new = NFT()

        if nft_info.owner:
            new.owner = await self.__get_or_create_related(NFTOwner, nft_info.owner)
        new.model = await self.__get_or_create_related(NFTModel, nft_info.model)
        new.backdrop = await self.__get_or_create_related(NFTBackdrop, nft_info.backdrop)
        new.symbol = await self.__get_or_create_related(NFTSymbol, nft_info.symbol)

        await new.asave()

        # Увеличиваем счётчик проиндексированных NFT
        self.__collection.indexed += 1
        await self.__collection.asave()

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
