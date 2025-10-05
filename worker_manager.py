from typing import List

from worker import Worker


class WorkerManager:
    """
    Manager worker'ов
    Работа с Worker инстансами происходит исключительно через этот Manager
    Singleton
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        if not isinstance(cls._instance, cls):
            cls._instance = super(WorkerManager, cls).__new__(cls)
            cls._initialized = False
        return cls._instance

    def __init__(self, *args, **kwargs):
        if not self.__class__._initialized:
            self.__class__._initialized = True  # set initial flag to True
            self.init()

    def init(self):
        self.__workers: List[Worker] = []

    async def create_workers(self):
        async for collection in NFTCollection.objects.all():
            self.__workers.append(Worker(collection))

    def run_workers(self):
        for worker in self.__workers:
            worker.run()