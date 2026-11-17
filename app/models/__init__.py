from app.models.catalogue import (  # noqa: F401
    Album, Artist, ExternalLink, Genre, Song, SongArtist, artist_genres, song_genres,
)
from app.models.community import ArtistFollow, Comment, CommentReport, Reaction  # noqa: F401
from app.models.content import ArtistUpdate  # noqa: F401
from app.models.data import ArtistExternalId, DataSource, MetricSnapshot  # noqa: F401
from app.models.user import User  # noqa: F401