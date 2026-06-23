we want to provode following cli commands :

t / test       --> test.sh  ---> pass the actual directory.
ti / testi / testintegration  --> test_integration_???_<commment>.sh
c / commit  --> commit.sh


create a new command, same pattern as our other commands, command : bump bmp b , subcommands ma/major m/minor p/patch --> bump_major_010_bump.sh, bump_minor_010.sh, bump_patch_010.sh
create a small standalon python script who does the heavvy lifting and is called by that shellscripts: 
- increment major/minor/patch in pyproj.toml
- rename the top [unreleased] section in changelog to the new version number, and put date and time local like : 
"[1.0.1] yyyy-mm-dd hh:mm:ss"  localtime
- if there is no [unreleased] section in changelog just create the new entry
- after that, create a new [unreleased] section above that 

create a new command, same pattern as our other commands, command : dependencies deps d , optional subcommands u,update, optional -u/--update  --> dependencies_010_dependencies.sh, dependencies_update_010_dependencies_update.sh
use a small standalon python script who does the heavvy lifting and is called by that shellscripts: 
adopt _dependencies.py and refractor it to your needs
d / deps / dependencies --update
du / depsupdate / dependencies_update


create a new command, same pattern as our other commands, command : clean, cln, cl  --> clean_010_clean.sh
use a small standalon python script who does the heavvy lifting and is called by that shellscripts: 
adopt _clean.py and refractor it to your needs


create a new command, same pattern as our other commands, command : codecov, coverage, cov  --> cov_010_coverage.sh
use a small standalon python script who does the heavvy lifting and is called by that shellscripts: 
adopt __coverage.py and refractor it to your needs. check for the .env file in BMK_PROJECT_DIR


create a new command, same pattern as our other commands, command : build, bld, b   --> bld_010_build.sh,
that builds the python project



create a new command, same pattern as our other commands, command : p, psh, push  --> 
push_010_update_deps.sh (calls deps via stagerunner)
push_020_test.sh (calls test via stagerunner)
push_030_commit.sh (calls commit via stagerunner)
push_040_push.sh (push like : "git", "push", "-u", remote, branch) - find a good way to pass the commit message from commit to the push command. take care that there is no env remaining for the next run 


create a new command, same pattern as our other commands, command : r, rel, release  --> 
release_010_release.sh
use a small standalon python script who does the heavvy lifting and is called by that shellscripts:
adopt _release.py and refractor it to your needs.


create a new command, same pattern as our other commands, command : run  --> 
run_010_run.sh
use a small standalon python script who does the heavvy lifting and is called by that shellscripts:
adopt _run.py and refractor it to your needs.

mk_push - no options, no commands . everything is passed through as commit message
_run.py must not accept any options or commands . everything is passed through as commands or options to the called script !


m / mnu / menue



prompts for claude : 

check cves in pyproj.toml

check notebook !

look for broken links in mdfiles
