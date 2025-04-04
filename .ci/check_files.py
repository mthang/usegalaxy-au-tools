import argparse
import yaml
import sys
import os

from bioblend.toolshed import ToolShedInstance
from bioblend.toolshed.repositories import ToolShedRepositoryClient

default_tool_shed = 'toolshed.g2.bx.psu.edu'

mandatory_keys = ['name', 'tool_panel_section_label', 'owner']
valid_keys = mandatory_keys + [
    'revisions', 'tool_shed_url', 'install_tool_dependencies',
    'install_resolver_dependencies', 'install_repository_dependencies',
]

valid_section_labels = [
    "Alignment",
    "Annotation",
    "Assembly",
    "BB Tools",
    "BED",
    "Bacterial Typing",
    "Blast +",
    "Built-in Converters",
    "ChemicalToolBox",
    "ChiP-seq",
    "Climate Analysis",
    "Collection Operations",
    "Convert Formats",
    "DNA Metabarcoding",
    "DeepTools",
    "EMBOSS",
    "Epigenetics",
    "Expression Tools",
    "Extract Features",
    "FASTA/FASTQ",
    "FASTQ Quality Control",
    "Fetch Sequences/Alignments",
    "Filter and Sort",
    "GATK Tools",
    "GATK Tools 1.4",
    "Gemini Tools",
    "Genome Editing",
    "Get Data",
    "Graph/Display Data",
    "HCA Single-cell",
    "HiCExplorer",
    "Imaging",
    "Join, Subtract and Group",
    "Lift-Over",
    "Machine Learning",
    "Mapping",
    "Metabolomics",
    "Metagenomic Analysis",
    "MiModD",
    "Mothur",
    "Multiple Alignments",
    "Nanopore",
    "None",
    "Operate on Genomic Intervals",
    "Other Tools",
    "Phylogenetics",
    "Picard",
    "Proteomic AI",
    "Proteomics",
    "QIIME 2",
    "Qualimap",
    "RAD-seq",
    "RNA-seq",
    "RSeQC",
    "SAM/BAM",
    "Send Data",
    "Single-cell",
    "Species abundance",
    "Statistics",
    "Text Manipulation",
    "VCF/BCF",
    "Variant Calling",
    "Variant Detection",
    "Viral Tools",
    "iVar",
]


def main():
    parser = argparse.ArgumentParser(description="Lint tool input files for installation on Galaxy")
    parser.add_argument('-f', '--files', help='Tool input files', nargs='+')
    parser.add_argument('-u', '--staging_url', help='Galaxy staging server URL')
    parser.add_argument('-g', '--production_url', help='Galaxy production server URL')
    parser.add_argument('-s', '--staging_dir', help='Staging server tool file directory')
    parser.add_argument('-p', '--production_dir', help='Production server tool file directory')

    args = parser.parse_args()
    files = args.files
    staging_dir = args.staging_dir
    production_dir = args.production_dir
    staging_url = args.staging_url
    production_url = args.production_url

    loaded_files = yaml_check(files)   # load yaml and raise ParserError if yaml is incorrect
    key_check(loaded_files)
    tool_list = join_lists([x['yaml']['tools'] for x in loaded_files])
    installable_warnings, installable_errors = check_installable(tool_list)
    installed_warnings_production, installed_errors_production = check_against_installed_tools(tool_list, production_dir, production_url)

    all_warnings = (
        installed_warnings_production + installable_warnings
    )
    all_errors = installable_errors + installed_errors_production
    for warning in all_warnings:
        sys.stderr.write('Warning: %s\n' % warning)
    if all_errors:
        sys.stderr.write('\n')
        for error in all_errors:
            sys.stderr.write('Error: %s\n' % error)
        raise Exception('Errors found')
    else:
        sys.stderr.write('\nAll tools are installable and not already installed on %s\n' % production_url)


def join_lists(list_of_lists):
    return [entry for list in list_of_lists for entry in list]


def yaml_check(files):
    loaded_files = []
    for file in files:
        with open(file) as file_in:
            # As a first pass, check that yaml loads
            try:
                loaded_yml = yaml.safe_load(file_in.read())  # might throw exception here
            except yaml.parser.ParserError as e:
                raise e
            loaded_files.append({
                'yaml': loaded_yml,
                'filename': file,
            })
    return loaded_files


def key_check(loaded_files):
    for loaded_file in loaded_files:
        sys.stderr.write('Checking %s \t ' % loaded_file['filename'])
        if 'tools' not in loaded_file['yaml'].keys():
            sys.stderr.write('ERROR\n')
            raise Exception('Error in %s: Expecting .yml file with \'tools\'. Check requests/template/template.yml for an example.' % loaded_file['filename'])
        tools = loaded_file['yaml']['tools']
        if not isinstance(tools, list):
            tools = [tools]
        for tool in tools:
            for key in mandatory_keys:
                if key not in tool.keys():
                    sys.stderr.write('ERROR\n')
                    raise Exception('Error in %s: All tool list entries must have \'%s\' specified. Check requests/template/template.yml for an example.' % (loaded_file['filename'], key))
            if 'tool_panel_section_id' in tool.keys():
                # Prevent people from having both label and id specified as this
                # can lead to tools being installed outside of sections
                raise Exception('Error in %s: tool_panel_section_id must not be specified.  Use tool_panel_section_label only.')
            for key in tool.keys():
                if key not in valid_keys:
                    raise Exception('%s is not a valid key.  Valid keys are [%s]' % (key, ', '.join(valid_keys)))
            label = tool['tool_panel_section_label']
            if label not in valid_section_labels:
                raise Exception('Error in %s:  tool_panel_section_label %s is not valid' % (loaded_file['filename'], label))
        sys.stderr.write('OK\n')


def check_installable(tools):
    # Go through all tool_shed_url values in request files and run get_ordered_installable_revisions
    # to ascertain whether the specified revision is installable
    errors = []
    warnings = []
    tools_by_shed = {}
    for tool in tools:
        if 'tool_shed_url' not in tool.keys():
            tool.update({'tool_shed_url': default_tool_shed})
        if tool['tool_shed_url'] in tools_by_shed.keys():
            tools_by_shed[tool['tool_shed_url']].append(tool)
        else:
            tools_by_shed[tool['tool_shed_url']] = [tool]

    for shed in tools_by_shed.keys():
        url = 'https://%s' % shed
        toolshed = ToolShedInstance(url=url)
        repo_client = ToolShedRepositoryClient(toolshed)

        for counter, tool in enumerate(tools_by_shed[shed]):
            try:
                installable_revisions = repo_client.get_ordered_installable_revisions(tool['name'], tool['owner'])
                if counter == 0:
                    sys.stderr.write('Connected to toolshed %s\n' % url)
                installable_revisions = [str(r) for r in installable_revisions][::-1]  # un-unicode and list most recent first
                if not installable_revisions:
                    errors.append('Tool with name: %s, owner: %s and tool_shed_url: %s has no installable revisions' % (tool['name'], tool['owner'], shed))
                    continue
            except Exception as e:
                raise Exception(e)

            if 'revisions' in tool.keys():  # Check that requested revisions are installable
                # 18/07/24: Downgrade this to a warning. Galaxy will either install the next installable revision or skip because it's already there
                for revision in tool['revisions']:
                    if revision not in installable_revisions:
                        warnings.append('%s revision %s is not installable' % (tool['name'], revision))
            else:
                tool.update({'revisions': [installable_revisions[0]]})
    return warnings, errors


def check_against_installed_tools(tool_list, tool_dir, url):
    errors = []
    warnings = []
    installed_tools = []
    for file in os.listdir(tool_dir):
        with open(tool_dir + '/' + file) as tool_yml:
            installed_tools += yaml.safe_load(tool_yml.read())['tools']
    for tool in tool_list:
        label_mismatch = False
        mismatched_labels = []
        name, owner = tool['name'], tool['owner']
        matching_installed_tools = [t for t in installed_tools if t['name'] == name and t['owner'] == owner]
        for installed_tool in matching_installed_tools:
            label_mismatch = installed_tool['tool_panel_section_label'] != tool['tool_panel_section_label']
            if label_mismatch:
                mismatched_labels.append(installed_tool["tool_panel_section_label"])
            matching_revisions = [rev for rev in tool['revisions'] if rev in installed_tool['revisions']]
            for revision in matching_revisions:
                warning = 'Tool %s revision %s is already installed on %s' % (name, revision, url)
                warnings.append(warning)
        if label_mismatch:
            error = "Tool %s is already installed  in a different section: '%s'" % (
                name, ", ".join(mismatched_labels)
            )
            errors.append(error)
    return warnings, errors


if __name__ == "__main__":
    main()
