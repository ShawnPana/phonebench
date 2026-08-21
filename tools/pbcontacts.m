// pbcontacts — seed/remove/count contacts inside a simulator, the sanctioned
// way (CNContactStore), so the UI, index, and daemons all agree.
//   pbcontacts add "Carol" "Phonebench" "555-0142"
//   pbcontacts remove "Carol" "Phonebench"
//   pbcontacts count
@import Contacts;
@import Foundation;

int main(int argc, char **argv) {
    @autoreleasepool {
        CNContactStore *store = [CNContactStore new];
        NSString *cmd = argc > 1 ? @(argv[1]) : @"count";
        NSError *err = nil;
        if ([cmd isEqualToString:@"add"]) {
            CNMutableContact *c = [CNMutableContact new];
            c.givenName = @(argv[2]); c.familyName = @(argv[3]);
            c.phoneNumbers = @[[CNLabeledValue labeledValueWithLabel:CNLabelPhoneNumberMobile
                value:[CNPhoneNumber phoneNumberWithStringValue:@(argv[4])]]];
            CNSaveRequest *req = [CNSaveRequest new];
            [req addContact:c toContainerWithIdentifier:nil];
            BOOL ok = [store executeSaveRequest:req error:&err];
            printf("{\"ok\": %s%s%s}\n", ok ? "true" : "false",
                   err ? ", \"error\": \"" : "", err ? [[err localizedDescription] UTF8String] : "");
            return ok ? 0 : 1;
        }
        // enumerate + filter by exact given/family name: the name predicate
        // misses vCard-imported contacts, enumeration never does
        NSString *g = argc > 2 ? @(argv[2]) : nil, *f = argc > 3 ? @(argv[3]) : nil;
        NSArray *keys = @[CNContactGivenNameKey, CNContactFamilyNameKey, CNContactPhoneNumbersKey];
        NSMutableArray *found = [NSMutableArray new];
        CNContactFetchRequest *fr = [[CNContactFetchRequest alloc] initWithKeysToFetch:keys];
        [store enumerateContactsWithFetchRequest:fr error:&err
            usingBlock:^(CNContact *c, BOOL *stop) {
                if (!g || ([c.givenName isEqualToString:g] &&
                           (!f || [c.familyName isEqualToString:f])))
                    [found addObject:c];
            }];
        if ([cmd isEqualToString:@"remove"]) {
            CNSaveRequest *req = [CNSaveRequest new];
            for (CNContact *c in found) [req deleteContact:[c mutableCopy]];
            BOOL ok = [store executeSaveRequest:req error:&err];
            printf("{\"ok\": %s, \"removed\": %lu}\n", ok || found.count == 0 ? "true" : "false",
                   (unsigned long)found.count);
            return 0;
        }
        printf("{\"ok\": true, \"count\": %lu}\n", (unsigned long)found.count);
        return 0;
    }
}
