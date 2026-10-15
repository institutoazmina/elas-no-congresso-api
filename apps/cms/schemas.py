from ninja import Schema


class CmsImageSchema(Schema):
    url: str
    width: int
    height: int


class HeroPageSchema(Schema):
    title: str
    subtitle: str
    hero_image: CmsImageSchema
