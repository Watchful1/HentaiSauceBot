

class SauceNAO:
	def __init__(self):
		self.creator = None
		self.material = None
		self.author = None
		self.member = None
		self.deviantart_art = None
		self.deviantart_src = None
		self.pixev_art = None
		self.pixev_src = None
		self.gelbooru = None
		self.danbooru = None
		self.sankaku = None
		self.saucenao_link = None

	def update_if_none(self, key, value):
		if value is not None and getattr(self, key) is None:
			setattr(self, key, value)
