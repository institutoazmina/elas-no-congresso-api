from ninja import Schema


class CmsImageSchema(Schema):
    url: str
    width: int
    height: int


class HeroPageSchema(Schema):
    title: str
    subtitle: str
    hero_image: CmsImageSchema


class FeministAICategorySchema(Schema):
    name: str
    concept: str


class FeministAILimitationSchema(Schema):
    text: str


class FeministAIEvaluationMetricSchema(Schema):
    label: str
    url: str
    previous: str
    current: str
    trend: str


class FeministAIEvaluationPartitionSchema(Schema):
    label: str
    accuracy: str
    percentage: str
    count: str


class FeministAIThematicMetricSchema(Schema):
    label: str
    value: str


class FeministAIThematicPartitionSchema(Schema):
    label: str
    training: str
    validation: str
    test: str


class FeministAIOpenLinkSchema(Schema):
    label: str
    url: str


class FeministAIPageSchema(Schema):
    seo_title: str
    seo_description: str
    title: str
    subtitle: str
    hero_image: CmsImageSchema
    content: str


class AboutPartnerSchema(Schema):
    name: str
    logo_url: str


class AboutTeamMemberSchema(Schema):
    name: str
    role: str


class AboutTeamGroupSchema(Schema):
    key: str
    title: str
    wide: bool
    members: list[AboutTeamMemberSchema]


class AboutPageSchema(Schema):
    seo_title: str
    seo_description: str
    title: str
    subtitle: str
    hero_image: CmsImageSchema
    content: str
    partners: list[AboutPartnerSchema]
    team: list[AboutTeamGroupSchema]


class HomePageSchema(Schema):
    seo_title: str
    seo_description: str
    title: str
    subtitle: str
    cta_text: str
    cta_url: str
    hero_image: CmsImageSchema
    content: str
    images: dict[str, CmsImageSchema]


class FooterAlertsPageSchema(Schema):
    title: str
    text: str
    cta_text: str
    cta_url: str
