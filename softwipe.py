#!/usr/bin/env python3
"""
The main module of softwipe. Here, command line arguments get parsed and the pipeline gets started.
"""

import argparse
import sys
import os

import strings
import compile_phase
import static_analysis_phase
import execution_phase
import util
import automatic_tool_installation
import scoring


def parse_arguments():
    """
    Parse command line arguments.
    :return: The "args" Namespace that contains the command line arguments specified by the user.
    """
    # Preparser, used for the command file & execute file help. Without the preparser, one would get an error because
    # 'programdir' is a required argument but is missing. With the preparser, the help can be printed anyway.
    preparser = argparse.ArgumentParser(add_help=False)
    preparser.add_argument('--commandfilehelp', default=False, action='store_true')
    preparser.add_argument('--executefilehelp', default=False, action='store_true')
    preargs, unk = preparser.parse_known_args()

    # Both helps can be printed at once
    if preargs.executefilehelp:
        print(strings.EXECUTE_FILE_HELP)
    if preargs.commandfilehelp:
        print(strings.COMMAND_FILE_HELP)
    if preargs.executefilehelp or preargs.commandfilehelp:  # Exit if either one or both helps have been printed
        sys.exit(0)

    # Main parser
    parser = argparse.ArgumentParser(description='Check the software quality of a C/C++ program\n\n'
                                                 'Important arguments you probably want to use:\n'
                                                 '  -c/-C to tell me whether your program is C or C++\n'
                                                 '  -M/-m/-l to tell me how to build your program\n'
                                                 '  -e to specify a file that tells me how to execute your program\n'
                                                 'Example command line for a CMake-based C++ program:\n'
                                                 './softwipe.py -CM path/to/program -e path/to/executefile\n',
                                     formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument('programdir', help="the root directory of your target program")

    c = parser.add_mutually_exclusive_group()
    c.add_argument('-c', '--cc', action='store_true', help='use C. This is the default option')
    c.add_argument('-C', '--cpp', action='store_true', help='use C++')

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('-M', '--cmake', action='store_true', help='compile the program using cmake. This is the default '
                                                                 'option')
    mode.add_argument('-m', '--make', action='store_true', help='compile the program using make. Note that this '
                                                                'option requires a "standard" style makefile that '
                                                                'uses common variables like ${CC}, ${CFLAGS}, '
                                                                '${LDFLAGS} etc. to work properly')
    mode.add_argument('-l', '--clang', nargs='+', metavar='target', help='compile the program using the clang/clang++ '
                                                                         'compiler. This option takes as arguments the'
                                                                         ' files to compile')

    parser.add_argument('-e', '--executefile', nargs=1, help='path to an "execute file" which contains a command line '
                                                             'that executes your program')
    parser.add_argument('--executefilehelp', action='store_true', help='print detailled information about how the '
                                                                       'execute file works and exit')

    parser.add_argument('-f', '--commandfile', nargs=1, help='path to a "command file" which can be used to provide '
                                                             'commands that should be executed for building a '
                                                             'make-based project or to provide compiler options for '
                                                             'building a simple compiler-based project')
    parser.add_argument('--commandfilehelp', action='store_true', help='print detailed information about how the '
                                                                       'command file works and exit')

    parser.add_argument('-x', '--exclude', nargs=1, help='a comma separated list of files and directories that should '
                                                         'be excluded from being analyzed by this program')

    parser.add_argument('-p', '--path', nargs=1, help='a comma separated list of paths that should be added to the '
                                                      'PATH environment variable. Use this if you have a dependency '
                                                      'installed but not accessible via your default PATH')

    parser.add_argument('--no-execution', action='store_true', help='Do not execute your program. This skips the '
                                                                    'clang sanitizer check')

    parser.add_argument('--allow-running-as-root', action='store_true', help='Do not print a warning if the user is '
                                                                             'root')

    args = parser.parse_args()
    return args


def add_to_path_variable(paths):
    """
    Add paths to the system PATH environment variable.
    :param paths: A comma separated list of paths to add.
    """
    path_list = []
    for path in paths.split(','):
        path_list.append(path)

    for path in path_list:
        os.environ['PATH'] += os.pathsep + path


def add_kwstyle_to_path_variable():
    """
    Adjusts the PATH variable by adding KWStyle to the PATH if it is contained in the softwipe directory (which it is
    if the user did the auto-installation of it).
    """
    kwstyle_dir = os.path.join(util.get_softwipe_directory(), 'KWStyle')
    if os.path.isdir(kwstyle_dir):
        add_to_path_variable(os.path.join(kwstyle_dir, strings.SOFTWIPE_BUILD_DIR_NAME))


def add_user_paths_to_path_variable(args):
    """
    Adjusts the PATH variable if necessary by adding user specified paths (if any were specified) to the PATH.
    :param args: The "args" Namespace as returned from parse_arguments().
    """
    user_paths = args.path[0] if args.path else None
    if user_paths:
        add_to_path_variable(user_paths)


def warn_if_user_is_root():
    """
    Check if the user is root, and print a warning if he is.
    """
    if os.geteuid() == 0:  # if user is root
        print(strings.USER_IS_ROOT_WARNING)
        while True:
            user_in = input('>>> ')
            if user_in == 'Y' or user_in == 'Yes':
                print("Okay, running as root now!")
                break
            elif user_in == 'n' or user_in == 'no':
                sys.exit(1)
            else:
                print('Please answer with "Y" (Yes) or "n" (no)!')


def compile_program(args, lines_of_code, cpp, compiler_flags, excluded_paths):
    """
    Run the automatic compilation of the target project.
    :param args: The "args" Namespace as returned from parse_arguments().
    :param lines_of_code: The lines of pure code count.
    :param cpp: Whether C++ is used or not. True if C++, False if C.
    :param compiler_flags: The flags to be used for compilation. Typically, these should be strings.COMPILE_FLAGS or,
    if no_execution, strings.COMPILER_WARNING_FLAGS.
    :param excluded_paths: A tupel containing the paths to be excluded.
    :return: The compiler score.
    """
    print(strings.RUN_COMPILER_HEADER)
    program_dir_abs = os.path.abspath(args.programdir)
    command_file = args.commandfile

    if args.make:
        if command_file:
            score = compile_phase.compile_program_make(program_dir_abs, lines_of_code, compiler_flags, excluded_paths,
                                                       make_command_file=command_file[0])
        else:
            score = compile_phase.compile_program_make(program_dir_abs, lines_of_code, compiler_flags, excluded_paths)
    elif args.clang:
        if command_file:
            score = compile_phase.compile_program_clang(program_dir_abs, args.clang, lines_of_code, compiler_flags,
                                                        excluded_paths, cpp, clang_command_file=command_file[0])
        else:
            score = compile_phase.compile_program_clang(program_dir_abs, args.clang, lines_of_code, compiler_flags,
                                                        excluded_paths, cpp)
    else:
        if command_file:
            score = compile_phase.compile_program_cmake(program_dir_abs, lines_of_code, compiler_flags, excluded_paths,
                                                        make_command_file=command_file[0])
        else:
            score = compile_phase.compile_program_cmake(program_dir_abs, lines_of_code, compiler_flags, excluded_paths)

    return score


def execute_program(program_dir_abs, executefile, cmake, lines_of_code):
    """
    Execute the program and parse the output of the clang sanitizers.
    :param program_dir_abs: The absolute path to the root directory of the target program.
    :param executefile: The executefile that contains a command line for executing the program.
    :param cmake: Whether CMake has been used for compilation or not.
    :param lines_of_code: The lines of pure code count.
    :return The weighted sanitizer error count.
    """
    try:
        weighted_error_count = execution_phase.run_execution(program_dir_abs, executefile, cmake, lines_of_code)
    except execution_phase.ExecutionFailedException as e:
        print(strings.WARNING_PROGRAM_EXECUTION_SKIPPED)
        weighted_error_count = 0
    return weighted_error_count


def compile_and_execute_program_with_sanitizers(args, lines_of_code, program_dir_abs, cpp, excluded_paths,
                                                no_exec=False):
    """
    Automatically compile and execute the program
    :param args: The "args" Namespace as returned from parse_arguments().
    :param lines_of_code: The lines of pure code count.
    :param program_dir_abs: The absolute path to the root directory of the target program.
    :param cpp: Whether C++ is used or not. True if C++, False if C.
    :param excluded_paths: A tupel containing the paths to be excluded.
    :param no_exec: If True, skip execution of the program.
    :return The compiler + sanitizer score.
    """
    compiler_flags = strings.COMPILER_WARNING_FLAGS if no_exec else strings.COMPILE_FLAGS
    weighted_sum_of_compiler_warnings = compile_program(args, lines_of_code, cpp, compiler_flags, excluded_paths)
    if not no_exec:
        execute_file = args.executefile[0] if args.executefile else None
        weighted_sum_of_sanitizer_warnings = execute_program(program_dir_abs, execute_file, args.cmake, lines_of_code)
    else:
        weighted_sum_of_sanitizer_warnings = 0
        print(strings.WARNING_PROGRAM_EXECUTION_SKIPPED)

    weighted_warning_rate = (weighted_sum_of_compiler_warnings + weighted_sum_of_sanitizer_warnings) / lines_of_code
    score = scoring.calculate_compiler_and_sanitizer_score(weighted_warning_rate)
    scoring.print_score(score, 'Compiler + Sanitizer')

    return score


def static_analysis(source_files, lines_of_code, cpp):
    """
    Run all the static analysis.
    :param source_files: The list of source files to analyze.
    :param lines_of_code: The lines of pure code count for the source_files.
    :param cpp: Whether C++ is used or not. True if C++, False if C.
    :return: All the static analysis scores: assertion_score, cppcheck_score, clang_tidy_score,
    cyclomatic_complexity_score, warning_score, unique_score, kwstyle_score.
    """
    assertion_score, cppcheck_score, clang_tidy_score, cyclomatic_complexity_score, warning_score, unique_score, \
    kwstyle_score = static_analysis_phase.run_static_analysis(source_files, lines_of_code, cpp)
    return assertion_score, cppcheck_score, clang_tidy_score, cyclomatic_complexity_score, warning_score, \
           unique_score, kwstyle_score


def main():
    add_kwstyle_to_path_variable()

    # Allow the user to auto-install the dependencies by just running "./softwipe.py" without any arguments
    if len(sys.argv) == 1:
        automatic_tool_installation.check_if_all_required_tools_are_installed()

    args = parse_arguments()

    # Normal check for the dependencies
    if len(sys.argv) != 1:
        automatic_tool_installation.check_if_all_required_tools_are_installed()

    add_user_paths_to_path_variable(args)

    if not args.allow_running_as_root:
        warn_if_user_is_root()

    cpp = True if args.cpp else False
    program_dir_abs = os.path.abspath(args.programdir)
    exclude = args.exclude[0] if args.exclude else None
    excluded_paths = util.get_excluded_paths(program_dir_abs, exclude)

    source_files = util.find_all_source_files(program_dir_abs, excluded_paths)
    lines_of_code = util.count_lines_of_code(source_files)

    compiler_and_sanitizer_score = compile_and_execute_program_with_sanitizers(args, lines_of_code, program_dir_abs,
                                                                               cpp, excluded_paths, args.no_execution)
    assertion_score, cppcheck_score, clang_tidy_score, cyclomatic_complexity_score, warning_score, \
        unique_score, kwstyle_score = static_analysis(source_files, lines_of_code, cpp)

    all_scores = [compiler_and_sanitizer_score, assertion_score, cppcheck_score, clang_tidy_score,
                  cyclomatic_complexity_score, warning_score, unique_score, kwstyle_score]
    overall_score = scoring.average_score(all_scores)
    scoring.print_score(overall_score, 'Overall program')


if __name__ == "__main__":
    main()
