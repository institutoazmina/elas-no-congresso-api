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
    content: dict[str, str]
    images: dict[str, CmsImageSchema]
    categories: list[FeministAICategorySchema]
    limitations: list[FeministAILimitationSchema]
    evaluation_metrics: list[FeministAIEvaluationMetricSchema]
    evaluation_partitions: list[FeministAIEvaluationPartitionSchema]
    thematic_metrics: list[FeministAIThematicMetricSchema]
    thematic_partitions: list[FeministAIThematicPartitionSchema]
    open_links: list[FeministAIOpenLinkSchema]


class AboutTimelineEventSchema(Schema):
    date_prefix: str
    year: str
    description_before_link: str
    link_text: str
    link_url: str
    description_after_link: str
    tag: str


class AboutChallengeSchema(Schema):
    title: str
    text: str


class AboutPartnerSchema(Schema):
    name: str
    asset_key: str
    logo_url: str


class AboutPageSchema(Schema):
    content: dict[str, str]
    hero_image: CmsImageSchema
    timeline: list[AboutTimelineEventSchema]
    challenges: list[AboutChallengeSchema]
    partners: list[AboutPartnerSchema]


class HomePageSchema(Schema):
    content: dict[str, str]
    images: dict[str, CmsImageSchema]


class FooterAlertsPageSchema(Schema):
    title: str
    text: str
    cta_text: str
    cta_url: str
