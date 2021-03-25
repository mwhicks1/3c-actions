#!/usr/bin/env python3
# python3: Whee, type annotations!

# Script to generate .github/workflows/main.yml, since we need to generate many
# jobs with similar content and as far as we know, the workflow language has
# essentially no support for code reuse. :(

import itertools
import textwrap
from typing import List, NamedTuple, Optional


class BenchmarkComponent(NamedTuple):
    # Default: Same as the benchmark's friendly_name.
    friendly_name: Optional[str] = None
    # Default: The benchmark's main directory.
    subdir: Optional[str] = None
    # Relative to subdir. Default: Same directory.
    build_dir: Optional[str] = None


class BenchmarkInfo(NamedTuple):
    name: str
    friendly_name: str
    dir_name: str
    build_cmds: str
    # Please use the `-k` option to `make` or its analogue so we can catch as
    # many errors as possible on one workflow run.
    build_converted_cmd: str
    convert_extra: Optional[str] = None
    # Default: One component with all default properties.
    components: Optional[List[BenchmarkComponent]] = None


# Standard options for `ninja` and parallel `make`.
#
# - `-j` and `--output-sync` make `make` behave more like `ninja`.
#
# - For both tools, `-l` is a crude attempt to try to avoid bogging down the
#   machine by using too much memory if other jobs are running on the machine.
#   If (for example) multiple ninja instances run concurrently, each will try to
#   run approximately `$(nproc)` parallel jobs, which can make a machine
#   unresponsive. (Anecdotal evidence suggests that `nice` is insufficient to
#   avoid the problem because it only directly controls CPU priority.) We set
#   `-l` to `$(nproc)` to try to use all hyperthreads when the machine is
#   otherwise idle; to a first approximation, there should be no benefit to
#   setting it higher. We hope that the resulting total memory usage is not too
#   much.
#
# TODO: Factor these out into wrapper scripts that users can call manually for
# all their builds?
ninja_std = 'ninja -l $(nproc)'
make_std = 'make -j $(nproc) -l $(nproc) --output-sync'

# Encapsulate the standard option to use the Checked C compiler for either a
# CMake project or a `make` project that uses the traditional CC variable.
make_checkedc = f'{make_std} CC="${{{{env.builddir}}}}/bin/clang"'
cmake_checkedc = 'cmake -DCMAKE_C_COMPILER=${{env.builddir}}/bin/clang'

# There is a known incompatibility between the vsftpd version we're using and
# Clang: vsftpd triggers a -Wenum-conversion warning that becomes an error with
# -Werror. See, for example:
#
# https://bugs.freebsd.org/bugzilla/show_bug.cgi?id=170101
#
# For now, we avoid the problem by turning off -Wenum-conversion. Unfortunately,
# the vsftpd makefile doesn't give us a way to add one flag to its CFLAGS list,
# so we stuff the flag in CC instead.
vsftpd_make = f'{make_std} CC="${{{{env.builddir}}}}/bin/clang -Wno-enum-conversion"'

ptrdist_components = ['anagram', 'bc', 'ft', 'ks', 'yacr2']

# The blank comments below stop YAPF from reformatting things in ways we don't
# want; large data literals are a known weakness of YAPF
# (https://github.com/google/yapf#why-does-yapf-destroy-my-awesome-formatting).

benchmarks = [

    # Vsftpd
    BenchmarkInfo(
        #
        name='vsftpd',
        friendly_name='Vsftpd',
        dir_name='vsftpd-3.0.3',
        build_cmds=f'bear {vsftpd_make}',
        build_converted_cmd=f'{vsftpd_make} -k'),

    # PtrDist
    BenchmarkInfo(
        #
        name='ptrdist',
        friendly_name='PtrDist',
        dir_name='ptrdist-1.1',
        build_cmds=textwrap.dedent(f'''\
        for i in {' '.join(ptrdist_components)} ; do \\
          (cd $i ; bear {make_checkedc} LOCAL_CFLAGS="-D_ISOC99_SOURCE") \\
        done
        '''),
        build_converted_cmd=(
            f'{make_checkedc} -k LOCAL_CFLAGS="-D_ISOC99_SOURCE"'),
        components=[
            BenchmarkComponent(friendly_name=c, subdir=c)
            for c in ptrdist_components
        ]),

    # LibArchive
    BenchmarkInfo(
        #
        name='libarchive',
        friendly_name='LibArchive',
        dir_name='libarchive-3.4.3',
        build_cmds=textwrap.dedent(f'''\
        cd build
        {cmake_checkedc} -G Ninja -DCMAKE_C_FLAGS="-w -D_GNU_SOURCE" ..
        bear {ninja_std} archive
        '''),
        build_converted_cmd=f'{ninja_std} -k 0 archive',
        convert_extra=textwrap.dedent('''\
        --skip '/.*/(test|test_utils|tar|cat|cpio|examples|contrib|libarchive_fe)/.*' \\
        '''),
        components=[BenchmarkComponent(build_dir='build')]),

    # Lua
    BenchmarkInfo(
        #
        name='lua',
        friendly_name='Lua',
        dir_name='lua-5.4.1',
        build_cmds=textwrap.dedent(f'''\
        bear {make_checkedc} linux
        ( cd src ; \\
          clang-rename-10 -pl -i \\
            --qualified-name=main \\
            --new-name=luac_main \\
            luac.c )
        '''),
        # Undo the rename using sed because the system install of clang-rename
        # can't handle checked pointers. This works since "luac_main" only
        # appears in the locations where it was added as a result of the
        # original rename.
        build_converted_cmd=textwrap.dedent(f'''\
        sed -i "s/luac_main/main/" src/luac.c
        {make_checkedc} -k linux
        ''')),

    # LibTiff
    BenchmarkInfo(
        #
        name='libtiff',
        friendly_name='LibTiff',
        dir_name='tiff-4.1.0',
        build_cmds=textwrap.dedent(f'''\
        {cmake_checkedc} -G Ninja -DCMAKE_C_FLAGS="-w" .
        bear {ninja_std} tiff
        ( cd tools ; \\
          for i in *.c ; do \\
            clang-rename-10 -pl -i \\
              --qualified-name=main \\
              --new-name=$(basename -s .c $i)_main $i ; \\
          done)
        '''),
        build_converted_cmd=f'{ninja_std} -k 0 tiff',
        convert_extra=textwrap.dedent('''\
        --skip '/.*/tif_stream.cxx' \\
        --skip '.*/test/.*\.c' \\
        --skip '.*/contrib/.*\.c' \\
        ''')),

    # Zlib
    BenchmarkInfo(
        #
        name='zlib',
        friendly_name='ZLib',
        dir_name='zlib-1.2.11',
        build_cmds=textwrap.dedent(f'''\
        mkdir build
        cd build
        {cmake_checkedc} -G Ninja -DCMAKE_C_FLAGS="-w" ..
        bear {ninja_std} zlib
        '''),
        build_converted_cmd=f'{ninja_std} -k 0 zlib',
        convert_extra="--skip '/.*/test/.*' \\",
        components=[BenchmarkComponent(build_dir='build')]),

    # Icecast
    BenchmarkInfo(
        #
        name='icecast',
        friendly_name='Icecast',
        dir_name='icecast-2.4.4',
        build_cmds=textwrap.dedent(f'''\
        CC="${{{{env.builddir}}}}/bin/clang" ./configure
        bear {make_std}
        '''),
        build_converted_cmd=f'{make_std} -k'),
]

HEADER = '''\
# This file is generated by generate-workflow.py. To update this file, update
# generate-workflow.py instead and re-run it. Some things in this file are
# explained by comments in generate-workflow.py.

name: 3C benchmark tests

on:
  # Run every day at 3:00 AM EDT (i.e., 7 am UTC)
  schedule:
    - cron: "0 7 * * *"
  workflow_dispatch:
    inputs:
      branch:
        description: "Branch or commit ID of correctcomputation/checkedc-clang to run workflow on"
        required: true
        default: "main"

env:
  benchmark_tar_dir: "/home/github/checkedc-benchmarks"
  builddir: "${{github.workspace}}/b/ninja"
  benchmark_conv_dir: "${{github.workspace}}/benchmark_conv"
  branch_for_scheduled_run: "main"
  include_dir: "${{github.workspace}}/depsfolder/checkedc-clang/llvm/projects/checkedc-wrapper/checkedc/include"
  port_tools: "${{github.workspace}}/depsfolder/checkedc-clang/clang/tools/3c/utils/port_tools"

jobs:

  # Cleanup files left behind by prior runs
  clean:
    name: Clean
    runs-on: self-hosted
    steps:
      - name: Clean
        run: |
          rm -rf ${{env.benchmark_conv_dir}}
          mkdir -p ${{env.benchmark_conv_dir}}
          rm -rf ${{env.builddir}}
          mkdir -p ${{env.builddir}}
          rm -rf ${{github.workspace}}/depsfolder
          mkdir -p ${{github.workspace}}/depsfolder

  # Clone and build 3c and clang
  # (clang is needed to test compilation of converted benchmarks.)
  build_3c:
    name: Build 3c and clang
    needs: clean
    runs-on: self-hosted
    steps:
      - name: Check out the actions repository
        uses: actions/checkout@v2
        with:
          path: depsfolder/actions
      - name: Check that the workflow file is up to date with generate-workflow.py before running it
        run: |
          cd ${{github.workspace}}/depsfolder/actions
          ./generate-workflow.py
          git diff --exit-code

      - name: Branch or commit ID
        run: echo "${{ github.event.inputs.branch || env.branch_for_scheduled_run }}"
      - name: Check out the 3C repository and the Checked C system headers
        run: |
          git init ${{github.workspace}}/depsfolder/checkedc-clang
          cd ${{github.workspace}}/depsfolder/checkedc-clang
          git remote add origin https://github.com/correctcomputation/checkedc-clang
          git fetch --depth 1 origin "${{ github.event.inputs.branch || env.branch_for_scheduled_run }}"
          git checkout FETCH_HEAD
          git clone --depth 1 https://github.com/microsoft/checkedc ${{github.workspace}}/depsfolder/checkedc-clang/llvm/projects/checkedc-wrapper/checkedc

      - name: Build 3c and clang
        run: |
          cd ${{env.builddir}}
          # We'll be running the tools enough that it's worth spending the extra
          # time for an optimized build, and the easiest way to do that is to
          # use a "release" build. But we do want assertions and we do want
          # debug info in order to get symbols in assertion stack traces, so we
          # use -DLLVM_ENABLE_ASSERTIONS=ON and the RelWithDebInfo build type,
          # respectively. Furthermore, the tools rely on the llvm-symbolizer
          # helper program to actually read the debug info and generate the
          # symbolized stack trace when an assertion failure occurs. We could
          # build it here, but as of 2021-03-15, we just use Ubuntu's version
          # installed systemwide; it seems that llvm-symbolizer is a generic
          # tool and the difference in versions does not matter.
          cmake -G Ninja \\
            -DLLVM_TARGETS_TO_BUILD=X86 \\
            -DCMAKE_BUILD_TYPE="RelWithDebInfo" \\
            -DLLVM_ENABLE_ASSERTIONS=ON \\
            -DLLVM_OPTIMIZED_TABLEGEN=ON \\
            -DLLVM_USE_SPLIT_DWARF=ON \\
            -DLLVM_ENABLE_PROJECTS="clang" \\
            ${{github.workspace}}/depsfolder/checkedc-clang/llvm
          {ninja_std} 3c clang
          chmod -R 777 ${{github.workspace}}/depsfolder
          chmod -R 777 ${{env.builddir}}

  # Run Test for 3C
  test_3c:
    name: 3C regression tests
    needs: build_3c
    runs-on: self-hosted
    steps:
      - name: 3C regression tests
        run: |
          cd ${{env.builddir}}
          {ninja_std} check-3c

  # Convert our benchmark programs
'''

# For this exceptionally long string literal, the trade-off is in favor of
# replacing {ninja_std} ad-hoc rather than using an f-string, which would
# require us to escape all the curly braces.
HEADER = HEADER.replace('{ninja_std}', ninja_std)


class Step(NamedTuple):
    name: str
    run: str  # Trailing newline but not blank line

    def __str__(self):
        part1 = textwrap.dedent(f'''\
        - name: {self.name}
          run: |
        ''')
        part2 = textwrap.indent(self.run, 4 * ' ')
        return textwrap.indent(part1 + part2, 6 * ' ')


def ensure_trailing_newline(s: str):
    return s + '\n' if s != '' and not s.endswith('\n') else s


with open('.github/workflows/main.yml', 'w') as out:
    out.write(HEADER)
    for binfo in benchmarks:
        for expand_macros, alltypes in itertools.product((False, True),
                                                         (False, True)):
            variant = (('expand_macros_' if expand_macros else '') +
                       ('alltypes' if alltypes else 'no_alltypes'))
            variant_friendly = (('macro-expanded, ' if expand_macros else '') +
                                ('-alltypes' if alltypes else 'no -alltypes'))
            variant_dir = '${{env.benchmark_conv_dir}}/' + variant
            convert_extra = (ensure_trailing_newline(binfo.convert_extra)
                             if binfo.convert_extra is not None else '')
            build_converted_cmd = binfo.build_converted_cmd.rstrip('\n')
            # Python argparse thinks `--extra-3c-arg -alltypes` is two options
            # rather than an option with an argument.
            at_flag = '--extra-3c-arg=-alltypes \\\n' if alltypes else ''
            at_ignore_step = ' (ignore failure)' if alltypes else ''
            at_ignore_code = ' || true' if alltypes else ''

            out.write(f'''\

  test_{binfo.name}_{variant}:
    name: Test {binfo.friendly_name} ({variant_friendly})
    needs: build_3c
    runs-on: self-hosted
    steps:
''')

            full_build_cmds = textwrap.dedent(f'''\
            mkdir -p {variant_dir}
            cd {variant_dir}
            tar -xvzf ${{{{env.benchmark_tar_dir}}}}/{binfo.dir_name}.tar.gz
            cd {binfo.dir_name}
            ''') + ensure_trailing_newline(binfo.build_cmds)

            steps = [Step('Build ' + binfo.friendly_name, full_build_cmds)]

            components = binfo.components
            if components is None:
                components = [BenchmarkComponent(binfo.friendly_name)]

            for component in components:
                component_dir = f'{variant_dir}/{binfo.dir_name}'
                if component.subdir is not None:
                    component_dir += '/' + component.subdir
                component_friendly_name = (component.friendly_name or
                                           binfo.friendly_name)

                # yapf: disable
                convert_flags = textwrap.indent(
                    convert_extra +
                    '--expand_macros_before_conversion \\\n' +
                    '--includeDir ${{env.include_dir}} \\\n' +
                    '--prog_name ${{env.builddir}}/bin/3c \\\n' +
                    at_flag +
                    '--project_path .' +
                    (f' \\\n--build_dir {component.build_dir}'
                     if component.build_dir is not None else '') +
                    '\n',
                    2 * ' ')
                # yapf: enable
                steps.append(
                    Step(
                        'Convert ' + component_friendly_name,
                        textwrap.dedent(f'''\
                        cd {component_dir}
                        ${{{{env.port_tools}}}}/convert_project.py \\
                        ''') + convert_flags))

                steps.append(
                    Step(
                        'Build converted ' + component_friendly_name +
                        at_ignore_step,
                        # convert_project.py sets -output-dir=out.checked as
                        # standard.
                        textwrap.dedent(f'''\
                        cd {component_dir}
                        cp -r out.checked/* .
                        rm -r out.checked
                        ''') +
                        #
                        (f'cd {component.build_dir}\n'
                         if component.build_dir is not None else '') +
                        f'{build_converted_cmd}{at_ignore_code}\n'))

            # We want blank lines between steps but not after the last step of
            # the last benchmark.
            out.write('\n'.join(str(s) for s in steps))
