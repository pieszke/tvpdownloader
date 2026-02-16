from requests import get
import m3u8
from pathlib import Path
from urllib.request import urlretrieve
import subprocess
from itertools import chain
from argparse import ArgumentParser
from shutil import rmtree
from alive_progress import alive_bar

CACHE = Path(__file__).with_name(".cache")
CACHE.mkdir(exist_ok=True)


def download_video(id: int, output_path: str | Path):
    output_path = Path(output_path)
    assert not output_path.is_dir(), "Output path must be a file"
    if output_path.exists():
        print(f"{output_path} already exists, skipping...")
        return
    cache = CACHE / str(id)
    req = get(
        f"https://vod.tvp.pl/api/products/{id}/videos/playlist?platform=BROWSER&videoType=MOVIE"
    )
    req.raise_for_status()
    data = req.json()
    m3u8_url = data["sources"]["HLS"][0]["src"]
    print("Browser playback: ", m3u8_url)
    hls_src = m3u8.load(m3u8_url)
    hls_src.dump(cache / f"{id}.m3u8")
    v_idx = [pl for pl in hls_src.playlists if pl.stream_info.resolution[0] == 1920][
        0
    ]  # get 1080p stream
    f_cnt = 0
    if v_idx.media:
        a_idx = v_idx.media[0]  # get audio stream
        audio = m3u8.load(a_idx.absolute_uri)
        audio.dump(cache / a_idx.uri)
        f_cnt += len(audio.segment_map) + len(audio.segments)
        a_cfg, a_files = ("-i", a_idx.uri), chain(audio.segment_map, audio.segments)
    else:
        a_cfg, a_files = (), ()
    mp4 = m3u8.load(v_idx.absolute_uri)
    mp4.dump(cache / v_idx.uri)
    f_cnt += len(mp4.segment_map) + len(mp4.segments)
    with alive_bar(f_cnt, title=f"Downloading parts for {output_path.name}") as bar:
        for seg in chain(mp4.segment_map, mp4.segments, a_files):
            if not (cache / seg.uri).exists():
                urlretrieve(seg.absolute_uri, cache / seg.uri)
            bar()

    print("Merging parts into mp4...")
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "warning",
            "-i",
            v_idx.uri,
            *a_cfg,
            "-acodec",
            "copy",
            "-bsf:a",
            "aac_adtstoasc",
            "-vcodec",
            "copy",
            output_path.resolve(),
        ],
        cwd=cache,
        check=True,
    )
    print(f"'{output_path.resolve()}' downloaded successfully, removing cache...")
    # rmtree(cache)
    print(f"'{cache.resolve()}' removed")


def main(args=None):
    ap = ArgumentParser(prog="tvpdownloader", description="Download TVP VOD videos")
    ap.add_argument(
        "--clear-cache",
        help="Clear the cache directory before downloading",
        action="store_true",
    )
    ap.add_argument(
        "--season",
        help="Download the whole season provided episode is in",
        action="store_true",
    )
    ap.add_argument("url", help="TVP VOD URL")
    ap.add_argument(
        "-o",
        "--output",
        help="Output directory",
        dest="output",
        type=Path,
        default=Path.cwd(),
    )
    args = ap.parse_args(args)
    if args.clear_cache:
        print("Clearing cache...")
        rmtree(CACHE)
        CACHE.mkdir(exist_ok=True)
        print("Cache cleared")
    out: Path = args.output
    url: str = args.url
    if "vod.tvp.pl" not in url:
        print("Provided URL is not a TVP VOD URL.")
        exit(1)

    id = int(url.rsplit(",", 1)[1])
    req = get(f"https://vod.tvp.pl/api/products/vods/{id}?platform=BROWSER")
    req.raise_for_status()
    data = req.json()
    assert data["type_"] == "EPISODE", f"Unsupported resource type {data['type_']}"
    assert data["season"]["type_"] == "SEASON", "season data invalid"
    assert data["season"]["serial"]["type_"] == "SERIAL", "serial data invalid"

    if args.season:
        if not out.is_dir():
            out = out.parent
        req = get(
            f"https://vod.tvp.pl/api/products/vods/serials/{data['season']['serial']['id']}/seasons/{data['season']['id']}/episodes?lang=PL&platform=BROWSER"
        )
        req.raise_for_status()
        out /= data["season"]["title"]
        out.mkdir(exist_ok=True)

        episodes = req.json()
        for episode in episodes:
            print(
                f"Downloading '{data['season']['serial']['title']} {data['season']['title']} {episode['title']}'..."
            )
            download_video(episode["id"], out / f"{episode['title']}.mp4")
    else:
        print(
            f"Downloading '{data['season']['serial']['title']} {data['season']['title']} {data['title']}'..."
        )
        if out.is_dir():
            out /= f"{data['title']}.mp4"
        assert out.suffix == ".mp4", "Output file must have .mp4 extension"
        download_video(id, out)


if __name__ == "__main__":
    main()
