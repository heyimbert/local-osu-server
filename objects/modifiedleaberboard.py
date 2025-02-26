import os
import asyncio
import hashlib
from ext import glob
from pathlib import Path
from typing import Union
from typing import Optional
from typing import TypedDict
from objects.score import Score
from objects.beatmap import Beatmap
from objects.modifiedbeatmap import ModifiedBeatmap

ONLINE_PLAYS = dict[str, list[dict]]
OSU_API_BASE = 'https://osu.ppy.sh/api'

status_to_db = {
    1: 'ranked',
    2: 'approved',
    3: 'qualified',
    4: 'loved'
}

"""Map ranking types"""
NOTSUBMITTED = -1
PENDING = 0
UPDATEAVALIABLE = 1
RANKED = 2
APPROVED = 3
QUALIFIED = 4
LOVED = 5

"""Leaderboard types"""
LOCAL   = 0
TOP     = 1
MODS    = 2
FRIENDS = 3
COUNTRY = 4

FROM_API_TO_SERVER_STATUS = {
    4: LOVED,
    3: QUALIFIED,
    2: APPROVED,
    1: RANKED,
    0: PENDING,
    -1: PENDING, # wip
    -2: PENDING  # graveyard
}

STARTING_LB_FORMAT = (
    "{rankedstatus}|false|{mapid}|{setid}|{num_of_scores}\n0\n"
    "[bold:0,size:20]{artist_unicode}|{title_unicode}\n10.0\n"
)
SCORE_FORMAT = (
    "{score_id}|{username}|{score}|"
    "{maxcombo}|{count50}|{count100}|"
    "{count300}|{countmiss}|{countkatu}|"
    "{countgeki}|{perfect}|{enabled_mods}|{user_id}|"
    "{num_on_lb}|{time}|{replay_available}"
)
VALID_LB_STATUESES = (LOVED, QUALIFIED, RANKED, APPROVED)

class Params(TypedDict):
    filename: str
    mods: int
    mode: int
    rank_type: int
    set_id: int
    md5: str

BEATMAP = Union[Beatmap, ModifiedBeatmap]
class ModifiedLeaderboard:
    def __init__(self) -> None:
        self.scores: list[Score] = []
        self.bmap: Optional[BEATMAP] = None
        self.personal_score: Optional[Score] = None

    @property
    def lb_base_fmt(self) -> Optional[bytes]:
        if not self.bmap:
            return
        
        return STARTING_LB_FORMAT.format(
            rankedstatus = FROM_API_TO_SERVER_STATUS[self.bmap.approved],
            mapid = self.bmap.beatmap_id,
            setid = self.bmap.beatmapset_id,
            num_of_scores = len(self.scores),
            artist_unicode = self.bmap.artist_unicode or self.bmap.artist,
            title_unicode = self.bmap.title_unicode or self.bmap.title
        ).encode()

    @property
    def as_binary(self) -> bytes:
        if not self.bmap:
            return b'0|false'
        
        r = FROM_API_TO_SERVER_STATUS[self.bmap.approved]
        if r not in VALID_LB_STATUESES:
            return f'{r}|false'.encode()

        if not self.lb_base_fmt:
            return f'{r}|false'.encode()
        
        buffer = bytearray()
        buffer += self.lb_base_fmt

        if self.personal_score:
            if self.personal_score not in self.scores:
                num_on_lb = 1
            else:
                num_on_lb = self.scores.index(self.personal_score) + 1

            self.personal_score.score = int(self.personal_score.pp or 0)
            buffer += SCORE_FORMAT.format(
                **self.personal_score.as_leaderboard_score,
                num_on_lb = num_on_lb
            ).encode()
            buffer += b'\n'
        else:
            buffer += b'\n'
        
        len_scores = len(self.scores)
        for idx, s in enumerate(self.scores):
            idx += 1
            s.name = f'({idx}) {s.name}'
            buffer += SCORE_FORMAT.format(
                **s.as_leaderboard_score,
                num_on_lb = idx
            ).encode()
            if idx != len_scores:
                buffer += b'\n'
        
        return bytes(buffer)
    
    @classmethod
    async def from_client(
        cls, params: Params
    ) -> 'ModifiedLeaderboard':
        lb = cls()
        if params['md5'] not in glob.modified_beatmaps:
            modified_maps = tuple(glob.modified_txt.read_text().splitlines())
            
            set_path: Optional[Path] = None
            for map in modified_maps:
                split = map.split('.mp3 | ', 1)
                if len(split) < 2:
                    continue
                
                _, file_path = split

                fpath = Path(file_path)

                if glob.using_wsl:
                    filename = fpath.name.split("\\")[-1]
                else:
                    filename = fpath.parts[-1]

                if params['filename'] == filename:
                    set_path = fpath

                    if glob.using_wsl:
                        # call wslpath to get their linux path from the windows one
                        # TODO: this can be done manually (without wslpath),
                        #       to avoid the subprocess
                        wslpath_proc = await asyncio.subprocess.create_subprocess_exec(
                            'wslpath',
                            set_path,
                            stdin=asyncio.subprocess.DEVNULL,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.DEVNULL,
                        )
                        stdin, _ = await wslpath_proc.communicate()

                        set_path = Path(stdin.decode().removesuffix('\n'))

                    break

            if (
                not set_path or
                not set_path.exists()
            ):
                return lb

            orignal_value: Optional[Union[int, str]] = None
            for line in set_path.read_bytes().splitlines():
                try:
                    k, v = line.decode().lower().strip().split(':', 1)
                    if k != 'beatmapid':
                        continue
                    
                    v = int(v)

                    if v > 0:
                        orignal_value = v
                        break
                except:
                    continue
            
            if not orignal_value:
                map_folder = '/'.join(set_path.parts[:-1])
                for fname in os.listdir(map_folder):
                    if not fname.endswith('.osu'):
                        continue
                    
                    if (
                        fname[:-5].lower() in params['filename'].lower() and 
                        params['filename'].lower() != fname.lower()
                    ):
                        orignal_map = Path(map_folder) / fname
                        orignal_value = hashlib.md5(orignal_map.read_bytes()).hexdigest()
                        break

            if not orignal_value:
                return lb
            
            if isinstance(orignal_value, int):
                bmap = await Beatmap.from_id(orignal_value)
            else:
                bmap = await Beatmap.from_md5(orignal_value)
            
            if not bmap:
                return lb
            
            lb.bmap = bmap = ModifiedBeatmap.add_to_db(
                bmap, params, set_path, return_modified = True
            )

            if not bmap:
                return lb

        else:
            lb.bmap = bmap = await ModifiedBeatmap.from_md5(params['md5'])
            if not bmap:
                return lb

        ranked_status = FROM_API_TO_SERVER_STATUS[bmap.approved]
        if ranked_status not in VALID_LB_STATUESES:
            return lb
        
        if (
            not glob.player or 
            not glob.current_profile
        ):
            return lb

        key = f'{status_to_db[bmap.approved]}_plays'
        
        _player_scores: Optional[ONLINE_PLAYS] = \
        glob.current_profile['plays'][key]

        if not _player_scores:
            return lb
        
        if bmap.file_md5 not in _player_scores:
            return lb

        player_scores = _player_scores[bmap.file_md5]
        player_scores.sort(key = lambda s: s['score'], reverse = True)

        if params['rank_type'] == MODS:
            player_scores = [
                x for x in player_scores if 
                x['mods'] == params['mods']
            ]
            if not player_scores:
                return lb

        lb.personal_score = Score.from_dict(player_scores[0])
        lb.scores = [Score.from_dict(x) for x in player_scores]

        return lb