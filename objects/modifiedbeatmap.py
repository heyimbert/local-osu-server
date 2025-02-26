import utils
import functools
from ext import glob
from typing import Any
from pathlib import Path
import pyttanko as oppai
from typing import Optional
from typing import TypedDict
from objects.beatmap import Beatmap

parser = oppai.parser()

class Params(TypedDict):
    filename: str
    mods: int
    mode: int
    rank_type: int
    set_id: int
    md5: str

class ModifiedBeatmap:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(**kwargs)

        self.id: int
        self.md5: str
        self.setid: int
        self.title: str
        self.artist: str
        self.version: str
        self.max_combo: int
        self.file_path: Path
        self.rank_status: int
        self.file_content: str
        self.original_bmap: Beatmap
        self.title_unicode: Optional[str]
        self.artist_unicode: Optional[str]
    
    @functools.cached_property
    def map_file(self) -> oppai.beatmap:
        return parser.map(
            osu_file = self.file_content.splitlines()
        )

    def as_dict(self) -> dict:
        bmap = self.__dict__.copy()
        try: del bmap['map_file']
        except: pass

        if 'file_path' in bmap:
            bmap['file_path'] = str(bmap['file_path'])
        
        if 'original_bmap' in bmap:
            bmap['original_bmap'] = bmap['original_bmap'].as_dict()

        return bmap

    @property
    def in_db(self) -> bool:
        return self.md5 in glob.modified_beatmaps

    @property
    def beatmap_id(self) -> int:
        return self.id
    
    @property
    def beatmapset_id(self) -> int:
        return self.setid

    @property
    def file_md5(self) -> str:
        return self.md5

    @property
    def approved(self) -> int:
        return self.rank_status
    
    async def get_file(self) -> str:
        return self.file_content
    
    @classmethod
    async def from_md5(cls, md5: str) -> Optional['ModifiedBeatmap']:
        if md5 not in glob.modified_beatmaps:
            return
        
        bmap_dict = glob.modified_beatmaps[md5].copy()
        bmap_dict['file_path'] = Path(bmap_dict['file_path'])

        if 'original_bmap' not in bmap_dict:
            bmap_dict['original_bmap'] = await Beatmap.from_id(
                bmap_dict['id']
            )
        else:
            bmap_dict['original_bmap'] = Beatmap.from_dict(
                bmap_dict['original_bmap']
            )

        return cls(**bmap_dict)
    
    @classmethod
    def from_dict(cls, _dict: dict[str, Any]) -> 'ModifiedBeatmap':
        bmap = cls()
        bmap.__dict__.update(**_dict)

        bmap.file_path = Path(bmap.file_path)
        bmap.original_bmap = Beatmap.from_dict(bmap.original_bmap) # type: ignore

        return bmap

    @staticmethod
    def add_to_db(
        bmap: Beatmap, params: Params, 
        path_to_modified: Path, return_modified: bool = False
    ) -> Optional['ModifiedBeatmap']:
        if (md5 := params['md5']) in glob.modified_beatmaps:
            return

        lower_filename = params['filename'].lower()
        url_parsed =  ''.join([
            x.lower() for x in bmap.version 
            if x.isalpha() or x == ' '
        ])
        split = lower_filename.split(url_parsed)        
        version = f"[{bmap.version}{split[-1][:-4]}"

        file_content = path_to_modified.read_bytes().decode(errors='ignore')
        glob.modified_beatmaps[md5] = _dict = {
            'md5': md5,
            'rank_status': bmap.approved,
            'id': bmap.beatmap_id,
            'setid': bmap.beatmapset_id,
            'title': bmap.title,
            'artist': bmap.artist,
            'title_unicode': bmap.title_unicode,
            'artist_unicode': bmap.artist_unicode,
            'file_path': str(path_to_modified),
            'file_content': file_content,
            'max_combo': bmap.max_combo,
            'version': version,
            'original_bmap': bmap.as_dict()
        }

        utils.update_files()

        if return_modified:
            return ModifiedBeatmap.from_dict(
                _dict = _dict.copy()
            )