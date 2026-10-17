from ninja import Schema


class CmsImageSchema(Schema):
    url: str
    width: int
    height: int


class AlertsPageSchema(Schema):
    title: str
    subtitle: str
    hero_image: CmsImageSchema
