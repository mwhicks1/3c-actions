#!/usr/bin/env python3
# python3: Whee, type annotations!

# Script to generate .github/workflows/main.yml, since we need to generate many
# jobs with similar content and as far as we know, the workflow language has
# essentially no support for code reuse. :(

from abc import ABC, abstractmethod
from dataclasses import dataclass
import os
import textwrap
from typing import Dict, List, Optional, TextIO, Any


# To make `WorkflowConfig` definitions more concise, this `Variant` class does
# not include some extra flags that are currently done in Cartesian product with
# `Variant` objects. Currently, the only such extra flag is expand_macros.
@dataclass
class Variant:
    alltypes: bool
    extra_3c_args: List[str] = ''
    friendly_name_suffix: str = ''
    is_comparative_varient: bool = False


@dataclass
class BenchmarkComponent:
    # Default: Same as the benchmark's friendly_name.
    friendly_name: Optional[str] = None
    # Default: The benchmark's main directory.
    subdir: Optional[str] = None
    # Relative to subdir. Default: Same directory.
    build_dir: Optional[str] = None


@dataclass
class BenchmarkInfo:
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
    patch_dir: Optional[str] = None
    # Disallow this benchmark for comparative varients
    disallow_for_comparative_varients: bool = False

    def is_allowed(self, var: Variant):
        # Is this a fancy varient?
        return not self.disallow_for_comparative_varients or \
               not var.is_comparative_varient


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

# `-w`: We generally want to turn off all compiler warnings since there are many
# of them in the benchmarks and they distract us from the errors we need to fix.
# In some cases, warnings may clue us in to the cause of an error, and it may be
# useful to temporarily turn them back on for troubleshooting.
#
# Some benchmarks appear to have no warnings in the code anyway (good for them!)
# and/or have other -W flags in effect that we can't easily (and don't)
# override, but we still pass this to all benchmarks as standard to make a best
# effort to turn off warnings.
#
# `-ferror-limit=0`: By default, Clang stops issuing errors after the first 20
# errors in each translation unit. In some cases, that might be helpful to avoid
# letting a single root cause produce a huge number of errors that make the
# statistics a less useful measure of what actually needs to be fixed, but in
# other cases, ignoring errors in each file after the first 20 introduces a more
# or less arbitrary distortion in the statistics. Currently, we believe the
# second effect outweighs the first, so we turn off the error limit.
#
# There is enough variation in how we need to pass compiler options to different
# benchmarks that we don't factor out anything more here.
common_cflags = '-w -ferror-limit=0'

# There is a known incompatibility between the vsftpd version we're using and
# Clang: vsftpd triggers a -Wenum-conversion warning that becomes an error with
# -Werror. See, for example:
#
# https://bugs.freebsd.org/bugzilla/show_bug.cgi?id=170101
#
# For now, we avoid the problem by turning off -Wenum-conversion. Unfortunately,
# the vsftpd makefile doesn't give us a way to add one flag to its CFLAGS list,
# so we stuff the flag in CC instead.
#
# NOTE: -Wenum-conversion is redundant with -w in common_cflags, but we keep it
# in case we turn off -w.
vsftpd_make = f'{make_std} CC="${{{{env.builddir}}}}/bin/clang {common_cflags} -Wno-enum-conversion"'

# We use plain `make` and not `make_std` because it's not safe to build thttpd
# in parallel: the main and cgi-src Makefiles may try to build match.o in
# parallel, which would result in a duplicate compilation database entry (which
# breaks the macro expander) or possibly other corruption. Another possible
# workaround might be to force match.o to be built first, but it seems more
# reasonable to just turn off parallelism (despite the modest running time cost)
# than to hard-code the knowledge of the specific problem here.
#
# I wasn't able to find any way to add to thttpd's compiler flags short of this
# hack. Although thttpd uses Autoconf, it doesn't honor the CFLAGS variable
# passed to Autoconf, and any arguments added to the CC variable at
# `./configure` time seem to get discarded. As with vsftpd, we cannot add flags
# to any of the other variables used in the makefile without losing the existing
# flags. ~ Matt 2021-04-22
thttpd_make = f'make CC="${{{{env.builddir}}}}/bin/clang {common_cflags}"'

ptrdist_components = ['anagram', 'bc', 'ft', 'ks', 'yacr2']
ptrdist_manual_components = ['anagram', 'ft', 'ks', 'yacr2']

olden_components = ['bh', 'bisort', 'em3d', 'health', 'mst',
                    'perimeter', 'power', 'treeadd', 'tsp', 'voronoi']

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

    # Parson
    BenchmarkInfo(
        #
        name='Parson',
        friendly_name='Parson',
        dir_name='parson',
        build_cmds=f'bear {make_checkedc}',
        build_converted_cmd=f'{make_checkedc} -k'),

    # bignum
    BenchmarkInfo(
        #
        name='TinyBigNum',
        friendly_name='TinyBigNum',
        dir_name='tiny-bignum-c',
        build_cmds=f'bear {make_checkedc}',
        build_converted_cmd=f'{make_checkedc} -k'),

    # Olden
    BenchmarkInfo(
        #
        name='Olden',
        friendly_name='Olden',
        dir_name='Olden',
        convert_extra="--extra-3c-arg=-allow-unwritable-changes \\",
        build_cmds=textwrap.dedent(f'''\
    for i in {' '.join(olden_components)} ; do \\
      (cd $i ; bear {make_checkedc} LOCAL_CFLAGS="{common_cflags} -D_ISOC99_SOURCE") \\
    done
    '''),
        build_converted_cmd=(
            f'{make_checkedc} -k LOCAL_CFLAGS="{common_cflags} -D_ISOC99_SOURCE"'
        ),
        components=[
            BenchmarkComponent(friendly_name=c, subdir=c)
            for c in olden_components
        ]),

    # PtrDist
    BenchmarkInfo(
        #
        name='ptrdist',
        friendly_name='PtrDist',
        dir_name='ptrdist-1.1',
        # yacr2:
        #
        # - Patch to work around correctcomputation/checkedc-clang#374. For
        #   certain header files foo.h, foo.c defines a macro FOO_CODE that
        #   activates a different #if branch in foo.h that defines global
        #   variables instead of declaring them. This is an unusual practice:
        #   normally foo.h would declare the variables whether or not it is
        #   being included by foo.c, and then foo.c would additionally define
        #   them. We simulate the normal practice by copying only the parts of
        #   foo.h conditional on FOO_CODE to a new file foo_code.h, making foo.c
        #   include foo_code.h in addition to foo.h, and deleting the `#define
        #   FOO_CODE`.
        #
        # - Fix type conflict between `costMatrix` declaration and definition,
        #   exposed when both are in the same translation unit.
        #
        # bc:
        #
        # - global.h has lines like `EXTERN id_rec * name_tree` that become a
        #   definition when included by global.c and a declaration (with the
        #   same PSL) when included by any other translation unit. This confuses
        #   3C badly. If a declaration comes first, 3C ignores the definition
        #   because it has the same PSL and constrains the variable to wild,
        #   hurting the conversion rate. If the definition comes first, then 3C
        #   tries to make it checked. But per
        #   correctcomputation/checkedc-clang#374, the last rewrite wins, and
        #   that will be from a translation unit in which the construct is a
        #   declaration, so 3C bakes the `extern` keyword into global.h, so
        #   global.c no longer generates a definition and the post-conversion
        #   link fails. To get the result we want, we inline the `#include
        #   "global.h"` in global.c so we have definitions with PSLs different
        #   from those of the declarations.
        build_cmds=textwrap.dedent(f'''\
        ( cd yacr2
          sed -Ei 's/^long (.*costMatrix)/ulong \\1/' assign.h
          for header in *.h  ; do
            src="$(basename "$header" .h).c"
            new_header="$(basename "$header" .h)_code.h"
            test -e "$src" || continue
            sed -ne '/^#ifdef.*CODE/,/#else.*CODE/{{ /^#/!p; }}' "$header" >"$new_header"
            sed -i "/#define.*_CODE/d; /#include \\"$header\\"/a#include \\"$new_header\\"" "$src"
          done )
        ( cd bc
          sed -i '/^#include "global.h"$/d' global.c
          cat global.h >>global.c )
        for i in {' '.join(ptrdist_components)} ; do \\
          (cd $i ; bear {make_checkedc} LOCAL_CFLAGS="{common_cflags} -D_ISOC99_SOURCE") \\
        done
        '''),
        build_converted_cmd=(
            f'{make_checkedc} -k LOCAL_CFLAGS="{common_cflags} -D_ISOC99_SOURCE"'
        ),
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
        {cmake_checkedc} -G Ninja -DCMAKE_C_FLAGS="{common_cflags} -D_GNU_SOURCE" ..
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
        bear {make_checkedc} CFLAGS="{common_cflags}" linux
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
        {make_checkedc} -k CFLAGS="{common_cflags}" linux
        ''')),

    # LibTiff
    BenchmarkInfo(
        #
        name='libtiff',
        friendly_name='LibTiff',
        dir_name='tiff-4.1.0',
        build_cmds=textwrap.dedent(f'''\
        {cmake_checkedc} -G Ninja -DCMAKE_C_FLAGS="{common_cflags}" .
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
        '''),
        patch_dir='tiff-4.1.0_patches'),

    # Zlib
    BenchmarkInfo(
        #
        name='zlib',
        friendly_name='ZLib',
        dir_name='zlib-1.2.11',
        build_cmds=textwrap.dedent(f'''\
        mkdir build
        cd build
        {cmake_checkedc} -G Ninja -DCMAKE_C_FLAGS="{common_cflags}" ..
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
        # Turn off _GNU_SOURCE to work around the problem with transparent
        # unions for `struct sockaddr *`
        # (https://github.com/microsoft/checkedc/issues/441). `configure` was
        # generated from `configure.in` by autoconf, but we don't want to re-run
        # autoconf here, so just patch the generated file. :/
        build_cmds=textwrap.dedent(f'''\
        sed -i '/_GNU_SOURCE/d' configure
        CC="${{{{env.builddir}}}}/bin/clang" CFLAGS="{common_cflags}" ./configure
        bear {make_std}
        '''),
        build_converted_cmd=f'{make_std} -k'),

    # thttpd
    BenchmarkInfo(
        #
        name='thttpd',
        friendly_name='Thttpd',
        dir_name='thttpd-2.29',
        build_cmds=textwrap.dedent(f'''\
        CC="${{{{env.builddir}}}}/bin/clang" ./configure
        chmod -R 777 *
        bear {thttpd_make}
        '''),
        build_converted_cmd=f'{thttpd_make} -k',
        patch_dir='thttpd-2.29_patches'),
]

HEADER = '''\
# This file is generated by generate-workflow.py. To update this file, update
# generate-workflow.py instead and re-run it. Some things in this file are
# explained by comments in generate-workflow.py.

name: {workflow.name}

on:
{optional_schedule_trigger}  workflow_dispatch:
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
          # As of 2021-04-12, we're using CCI's `checkedc` repository because it
          # has a checked declaration for `syslog` that we want to use for our
          # experiments but have not yet submitted to Microsoft.
          git clone --depth 1 https://github.com/correctcomputation/checkedc ${{github.workspace}}/depsfolder/checkedc-clang/llvm/projects/checkedc-wrapper/checkedc

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


# Apparently Step has to be a dataclass in order for its field declaration to be
# seen by the dataclass implementation in the subclasses.
@dataclass
class Step(ABC):
    name: str

    @abstractmethod
    def format_body(self):
        raise NotImplementedError

    def __str__(self):
        step = (f'- name: {self.name}\n' +
                textwrap.indent(self.format_body(), 2 * ' '))
        return textwrap.indent(step, 6 * ' ')


@dataclass
class RunStep(Step):
    run: str  # Trailing newline but not blank line

    def format_body(self):
        return 'run: |\n' + textwrap.indent(self.run, 2 * ' ')


@dataclass
class ActionStep(Step):
    action_name: str
    args: Dict[str, Any]

    def format_body(self):
        formatted_args = ''.join(
            f'{arg_key}: {arg_val}\n' for arg_key, arg_val in self.args.items())
        return (textwrap.dedent(f'''\
            uses: {self.action_name}
            with:
        ''') + textwrap.indent(formatted_args, 2 * ' '))


def ensure_trailing_newline(s: str):
    return s + '\n' if s != '' and not s.endswith('\n') else s


def generate_benchmark_job(out: TextIO,
                           binfo: BenchmarkInfo,
                           expand_macros: bool,
                           variant: Variant,
                           generate_stats=False):
    # Check if this benchmark is allowed for the given varient
    if not binfo.is_allowed(variant):
        return

    # "Subvariant" = Variant object + the extra flags mentioned above. We use
    # the name "subvariant" even though the subvariants may be grouped by extra
    # flag value before variant. (Better naming ideas?)
    subvariant_name = (('' if expand_macros else 'no_') + 'expand_macros_' +
                       ('' if variant.alltypes else 'no_') + 'alltypes')

    subvariant_convert_extra = ''
    if variant.alltypes:
        # Python argparse thinks `--extra-3c-arg -alltypes` is two options
        # rather than an option with an argument.
        subvariant_convert_extra += '--extra-3c-arg=-alltypes \\\n'
    # XXX: An argument could be made for putting this before -alltypes for
    # consistency with the subvariant name. For now, I don't want the diff in
    # the generated workflow.
    if expand_macros:
        subvariant_convert_extra += '--expand_macros_before_conversion \\\n'

    for earg in variant.extra_3c_args:
        subvariant_convert_extra += '--extra-3c-arg=' + earg + ' \\\n'
        subvariant_name += '_' + earg.lstrip('-').replace('-', '_')

    subvariant_friendly = (('' if expand_macros else 'not ') +
                           'macro-expanded, ' +
                           ('' if variant.alltypes else 'no ') + '-alltypes' +
                           variant.friendly_name_suffix)
    subvariant_dir = '${{env.benchmark_conv_dir}}/' + subvariant_name
    benchmark_convert_extra = (ensure_trailing_newline(binfo.convert_extra)
                               if binfo.convert_extra is not None else '')
    build_converted_cmd = binfo.build_converted_cmd.rstrip('\n')
    at_filter_step = (' (filter bounds inference errors)'
                      if variant.alltypes else '')
    # By default, this shell script runs with the `pipefail` option off. This is
    # important so that the build failure doesn't cause the entire script to
    # fail regardless of the result of filter-bounds-inference-errors.py. But we
    # might want to turn on `pipefail` in general, in which case we'd need to
    # turn it back off here.
    at_filter_code = ('''\
 2>&1 | ${{github.workspace}}/depsfolder/actions/filter-bounds-inference-errors.py'''
                      if variant.alltypes else '')

    # The blank line below is important: it gets us blank lines between jobs
    # without a blank line at the very end of the workflow file.
    out.write(f'''\

  test_{binfo.name}_{subvariant_name}:
    name: Test {binfo.friendly_name} ({subvariant_friendly})
    needs: build_3c
    runs-on: self-hosted
    steps:
''')

    benchmark_dir = f'{subvariant_dir}/{binfo.dir_name}'

    apply_patch_cmd = ''
    if binfo.patch_dir:
        apply_patch_cmd = textwrap.dedent(f'''\
            for i in ${{{{env.benchmark_tar_dir}}}}/{binfo.patch_dir}/*; do patch -s -p0 < $i; done
        ''')
    change_dir = textwrap.dedent(f'''\
        cd {binfo.dir_name}
    ''')

    full_build_cmds = textwrap.dedent(f'''\
        mkdir -p {subvariant_dir}
        cd {subvariant_dir}
        tar -xvzf ${{{{env.benchmark_tar_dir}}}}/{binfo.dir_name}.tar.gz
    ''') + apply_patch_cmd + change_dir + ensure_trailing_newline(
        binfo.build_cmds)

    steps = [RunStep('Build ' + binfo.friendly_name, full_build_cmds)]

    components = binfo.components
    if components is None:
        components = [BenchmarkComponent(binfo.friendly_name)]

    defer_failure = (len(components) > 1)
    failed_components_fname = f'{benchmark_dir}/failed-components-list.txt'
    for component in components:
        component_dir = benchmark_dir
        if component.subdir is not None:
            component_dir += '/' + component.subdir
        component_friendly_name = (component.friendly_name or
                                   binfo.friendly_name)

        # yapf: disable
        convert_flags = textwrap.indent(
            benchmark_convert_extra +
            '--prog_name ${{env.builddir}}/bin/3c \\\n' +
            subvariant_convert_extra +
            '--project_path .' +
            (f' \\\n--build_dir {component.build_dir}'
             if component.build_dir is not None else '') +
            '\n',
            2 * ' ')
        # yapf: enable
        steps.append(
            RunStep(
                'Convert ' + component_friendly_name,
                textwrap.dedent(f'''\
                    cd {component_dir}
                    ${{{{env.port_tools}}}}/convert_project.py \\
                ''') + convert_flags))

        if generate_stats:
            perf_dir_name = "3c_performance_stats/"
            steps.append(
                RunStep(
                    'Copy 3c stats of ' + component_friendly_name,
                    textwrap.dedent(f'''\
                        cd {component_dir}
                        mkdir {perf_dir_name}
                        cp *.json {perf_dir_name}
                    ''')))
            # Same idea as the job name but using the component name instead of
            # the benchmark name.
            perf_artifact_name = f'{component_friendly_name}_{subvariant_name}'
            perf_dir = os.path.join(component_dir, perf_dir_name)
            steps.append(
                ActionStep(
                    'Upload 3c stats of ' + component_friendly_name,
                    'actions/upload-artifact@v2', {
                        'name': perf_artifact_name,
                        'path': perf_dir,
                        'retention-days': 5
                    }))

        defer_failure_step = (' (defer failure)' if defer_failure else '')
        defer_failure_code = (f'''\
 || echo {component_friendly_name} >>{failed_components_fname}'''
                              if defer_failure else '')
        steps.append(
            RunStep(
                'Build converted ' + component_friendly_name + at_filter_step +
                defer_failure_step,
                # convert_project.py sets -output-dir=out.checked as
                # standard.
                textwrap.dedent(f'''\
                    cd {component_dir}
                    if [ -e "out.checked" ]; then cp -r out.checked/* . && rm -r out.checked; fi
                ''') +
                #
                (f'cd {component.build_dir}\n'
                 if component.build_dir is not None else '') +
                f'{build_converted_cmd}{at_filter_code}{defer_failure_code}\n'))

    if defer_failure:
        steps.append(
            RunStep(
                'Check for deferred post-conversion build failures', f'''\
if [ -e {failed_components_fname} ]; then
    echo 'Failed components (see previous post-conversion build steps):'
    cat {failed_components_fname}
    exit 1
fi
'''))

    # We want blank lines between steps but not after the last step of
    # the last benchmark.
    out.write('\n'.join(str(s) for s in steps))


@dataclass
class WorkflowConfig:
    filename: str
    friendly_name: str
    variants: List[Variant]
    # Warning: If we have multiple scheduled workflows, the times need to be
    # well-separated because of
    # https://github.com/correctcomputation/actions/issues/6 .
    cron_timestamp: Optional[str] = None
    generate_stats: bool = False


workflow_file_configs = [
    WorkflowConfig(filename="main",
                   friendly_name="3C benchmark tests",
                   variants=[Variant(alltypes=False),
                             Variant(alltypes=True)],
                   cron_timestamp="0 5 * * *"),
    WorkflowConfig(
        filename="exhaustivestats",
        friendly_name="Exhaustive testing and Performance Stats",
        variants=[
            Variant(alltypes=False),
            Variant(alltypes=True)
        ],
        generate_stats=True),
    WorkflowConfig(
        filename="exhaustiveleastgreatest",
        friendly_name="Exhaustive testing and Performance Stats (Least and Greatest)",
        variants=[
            Variant(alltypes=True,
                    extra_3c_args=['-only-g-sol'],
                    friendly_name_suffix=', greatest solution',
                    is_comparative_varient=True),
            Variant(alltypes=True,
                    extra_3c_args=['-only-l-sol'],
                    friendly_name_suffix=', least solution',
                    is_comparative_varient=True),
        ],
        generate_stats=True),
    WorkflowConfig(
        filename="exhaustiveccured",
        friendly_name="Exhaustive testing and Performance Stats (CCured)",
        variants=[
            Variant(alltypes=True,
                    extra_3c_args=['-disable-rds'],
                    friendly_name_suffix=', CCured solution',
                    is_comparative_varient=True),
            Variant(alltypes=True,
                    extra_3c_args=['-disable-fnedgs'],
                    friendly_name_suffix=', FuncRevEdges solution',
                    is_comparative_varient=True),
        ],
        generate_stats=True)
]

for config in workflow_file_configs:
    with open(f'.github/workflows/{config.filename}.yml', 'w') as out:
        # format header using workflow name and schedule time.
        formatted_hdr = HEADER.replace('{workflow.name}', config.friendly_name)
        optional_schedule_trigger = (''
                                     if config.cron_timestamp is None else f'''\
  # Run every day at the following time.
  schedule:
    - cron: "{config.cron_timestamp}"
''')
        formatted_hdr = formatted_hdr.replace('{optional_schedule_trigger}',
                                              optional_schedule_trigger)

        out.write(formatted_hdr)
        for binfo in benchmarks:
            for expand_macros in (False, True):
                for variant in config.variants:
                    generate_benchmark_job(out, binfo, expand_macros, variant,
                                           config.generate_stats)
