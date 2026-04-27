from setuptools import setup, find_packages

pkg_name = "qobuz-dl"


def read_file(fname):
    with open(fname, "r") as f:
        return f.read()


requirements = [
    "pathvalidate",
    "requests",
    "mutagen",
    "tqdm",
    "pick==1.6.0",
    "beautifulsoup4",
    "colorama",
]

setup(
    name=pkg_name,
    version="0.9.10.0",
    author="Vitiko",
    author_email="vhnz98@gmail.com",
    description="The complete Lossless and Hi-Res music downloader for Qobuz",
    long_description=read_file("README.md"),
    long_description_content_type="text/markdown",
    url="https://github.com/vitiko98/Qobuz-DL",
    install_requires=requirements,
    extras_require={
        "dev": ["pytest>=7", "responses>=0.24"],
    },
    entry_points={
        "console_scripts": [
            "qobuz-dl = qobuz_dl:main",
            "qdl = qobuz_dl:main",
        ],
    },
    packages=find_packages(exclude=["tests", "tests.*"]),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "License :: OSI Approved :: GNU General Public License (GPL)",
        "Operating System :: OS Independent",
    ],
    # 3.8 went EOL Oct 2024; pytest 8.4+ and recent `responses` releases
    # have already dropped it. Keep runtime/test floor in sync.
    python_requires=">=3.9",
)

# rm -f dist/*
# python3 setup.py sdist bdist_wheel
# twine upload dist/*
